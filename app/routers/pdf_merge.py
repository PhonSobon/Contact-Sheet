"""Combine PDFs, inspect pages for the page editor, and build a PDF from a page plan."""

import base64
import io
import json
import logging
from typing import List

import fitz  # PyMuPDF
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from app.core.config import MAX_COMBINE_PDFS, MAX_INSPECT_PDFS, MAX_PAGES, MAX_PDF_BYTES
from app.core.pdf_utils import ensure_pdf_name, pdf_response, read_pdf_upload

router = APIRouter(prefix="/api/pdf", tags=["pdf"])
logger = logging.getLogger("contact_sheet")

THUMB_JPEG_QUALITY = 70


@router.post("/combine")
async def pdf_combine(
    files: List[UploadFile] = File(...),
    output_filename: str = Form("combined.pdf"),
):
    if len(files) < 2:
        raise HTTPException(400, "Please upload at least two PDFs to combine.")
    if len(files) > MAX_COMBINE_PDFS:
        raise HTTPException(400, f"Up to {MAX_COMBINE_PDFS} PDFs at a time.")

    out = fitz.open()
    opened_docs = []
    total_pages = 0
    try:
        for f in files:
            doc = await read_pdf_upload(f, MAX_PDF_BYTES)
            opened_docs.append(doc)

            total_pages += doc.page_count
            if total_pages > MAX_PAGES:
                raise HTTPException(400, f"Combined page count exceeds the {MAX_PAGES}-page limit.")
            out.insert_pdf(doc)

        buf = io.BytesIO()
        out.save(buf, garbage=4, deflate=True)
    finally:
        out.close()
        for doc in opened_docs:
            doc.close()

    return pdf_response(
        buf,
        ensure_pdf_name(output_filename, "combined.pdf"),
        {"X-Output-Pages": str(total_pages), "X-Output-Bytes": str(len(buf.getvalue()))},
    )


def _page_thumbnail(page: fitz.Page, matrix: fitz.Matrix) -> tuple:
    """Renders a JPEG thumbnail. JPEG instead of PNG keeps the JSON small for
    long or scanned PDFs (PNG thumbnails of scans made responses tens of MB).
    A page MuPDF can't render gets a blank placeholder instead of failing the
    whole upload — the page itself is still copied as-is when building."""
    try:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        logger.warning("Could not render page %d for thumbnail", page.number + 1, exc_info=True)
        rect = page.rect * matrix
        img = Image.new("RGB", (max(1, int(rect.width)), max(1, int(rect.height))), (235, 235, 235))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=THUMB_JPEG_QUALITY)
    data_url = f"data:image/jpeg;base64,{base64.b64encode(out.getvalue()).decode()}"
    return img.width, img.height, data_url


@router.post("/inspect")
async def pdf_inspect(
    files: List[UploadFile] = File(...),
    thumb_dpi: int = Form(90),
    # 0 = every page; otherwise only the first N pages get thumbnails (e.g. 1
    # for a cover preview). page_count still reports the full document.
    max_pages: int = Form(0),
):
    """Render low-res thumbnails for every page of every uploaded PDF, keyed by
    source_index so the frontend can build an editable page grid — and merge,
    since dropping multiple PDFs here just interleaves their pages."""
    if not files:
        raise HTTPException(400, "Please upload at least one PDF.")
    if len(files) > MAX_INSPECT_PDFS:
        raise HTTPException(400, f"Up to {MAX_INSPECT_PDFS} PDFs at a time.")

    zoom = max(24, min(200, thumb_dpi)) / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    sources = []
    total_pages = 0
    for src_idx, f in enumerate(files):
        doc = await read_pdf_upload(f, MAX_PDF_BYTES)
        try:
            total_pages += doc.page_count
            if total_pages > MAX_PAGES:
                raise HTTPException(400, f"Combined page count exceeds the {MAX_PAGES}-page limit.")

            page_count = doc.page_count
            pages = []
            for i, page in enumerate(doc):
                if max_pages > 0 and i >= max_pages:
                    break
                width, height, data_url = _page_thumbnail(page, matrix)
                pages.append(
                    {
                        "page_index": i,
                        "width": width,
                        "height": height,
                        "rotation": page.rotation,
                        "data_url": data_url,
                    }
                )
        finally:
            doc.close()

        sources.append(
            {
                "source_index": src_idx,
                "filename": f.filename,
                "page_count": page_count,
                "pages": pages,
            }
        )

    return JSONResponse({"sources": sources})


@router.post("/build")
async def pdf_build(
    files: List[UploadFile] = File(...),
    plan: str = Form(...),
    compress: str = Form("none"),  # "none" | "optimize" | "rasterize"
    raster_dpi: int = Form(120),
    raster_quality: int = Form(70),
    output_filename: str = Form("edited.pdf"),
):
    """Build a new PDF from the original source file(s) plus a page 'plan':
    a JSON list of {source_index, page_index, rotate} in the desired final
    order. Selecting a subset of pages implements delete/split/extract;
    listing multiple source_index values implements merge; 'rotate' is
    degrees added to whatever rotation the page already has."""
    try:
        plan_items = json.loads(plan)
    except Exception:
        raise HTTPException(400, "Malformed plan.")
    if not isinstance(plan_items, list) or len(plan_items) == 0:
        raise HTTPException(400, "The plan is empty — nothing to build.")
    if len(plan_items) > MAX_PAGES:
        raise HTTPException(400, f"Output would exceed the {MAX_PAGES}-page limit.")
    if compress not in ("none", "optimize", "rasterize"):
        raise HTTPException(400, "Unknown compress mode.")

    docs = {}
    out = fitz.open()
    try:
        for idx, f in enumerate(files):
            docs[idx] = await read_pdf_upload(f, MAX_PDF_BYTES)

        for item in plan_items:
            src_idx = item.get("source_index")
            page_idx = item.get("page_index")
            rotate = int(item.get("rotate", 0)) % 360
            src_doc = docs.get(src_idx)
            if src_doc is None:
                raise HTTPException(400, "Plan references a file that wasn't uploaded.")
            if page_idx is None or not (0 <= page_idx < src_doc.page_count):
                raise HTTPException(400, "Plan references an out-of-range page.")
            out.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)
            if rotate:
                new_page = out[out.page_count - 1]
                new_page.set_rotation((new_page.rotation + rotate) % 360)

        buf = io.BytesIO()
        if compress == "rasterize":
            _save_rasterized(out, buf, raster_dpi, raster_quality)
        else:
            out.save(buf, garbage=4, deflate=True, deflate_images=(compress == "optimize"))
    finally:
        out.close()
        for d in docs.values():
            d.close()

    return pdf_response(
        buf,
        ensure_pdf_name(output_filename, "edited.pdf"),
        {"X-Output-Bytes": str(len(buf.getvalue()))},
    )


def _save_rasterized(doc: fitz.Document, buf: io.BytesIO, raster_dpi: int, raster_quality: int) -> None:
    """Biggest size win — flattens each page to a JPEG, so any real text
    becomes unselectable. Good for photo-heavy/scanned PDFs."""
    raster_dpi = max(36, min(300, raster_dpi))
    matrix = fitz.Matrix(raster_dpi / 72.0, raster_dpi / 72.0)
    raster_doc = fitz.open()
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            jpg_io = io.BytesIO()
            img.save(jpg_io, format="JPEG", quality=max(1, min(95, raster_quality)))
            page_w = pix.width * 72.0 / raster_dpi
            page_h = pix.height * 72.0 / raster_dpi
            new_page = raster_doc.new_page(width=page_w, height=page_h)
            new_page.insert_image(fitz.Rect(0, 0, page_w, page_h), stream=jpg_io.getvalue())
        raster_doc.save(buf, garbage=4, deflate=True)
    finally:
        raster_doc.close()
