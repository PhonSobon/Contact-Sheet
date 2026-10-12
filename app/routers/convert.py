"""PDF -> images and images -> PDF."""

import base64
import io
import zipfile
from typing import List

import fitz  # PyMuPDF
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import Image

from app.core.config import (
    ALLOWED_OUTPUT_FORMATS,
    MAX_IMAGE_BYTES,
    MAX_PAGES,
    P2I_MAX_FILES,
    P2I_MAX_PAGES,
    P2I_MAX_PDF_BYTES,
)
from app.core.image_utils import flatten_to_rgb, open_image_bytes
from app.core.pdf_utils import base_name, read_pdf_upload

router = APIRouter(prefix="/api", tags=["convert"])

MAX_ESTIMATED_OUTPUT_BYTES = 200 * 1024 * 1024

# Full-resolution pages only go into the zip. The JSON response also
# carries a small on-screen preview per page (capped width, JPEG) instead
# of the full-res image as a second base64 copy — at 150+ DPI over many
# pages, embedding every full-res image twice made responses balloon to
# hundreds of MB and time out (e.g. a 25-page PDF at 150 DPI PNG produced
# a ~440 MB response). The zip still contains the requested format/DPI
# untouched; only the preview is downsized.
THUMB_MAX_WIDTH = 220


@router.post("/pdf-to-images")
async def pdf_to_images(
    files: List[UploadFile] = File(...),
    dpi: int = Form(150),
    output_format: str = Form("png"),
    # comma-separated "fileIndex:page" pairs (0-based file index, 1-based page) to skip entirely
    exclude_pages: str = Form(""),
):
    output_format = output_format.lower().strip()
    if output_format not in ALLOWED_OUTPUT_FORMATS:
        raise HTTPException(400, f"Unsupported output format '{output_format}'.")
    if dpi < 36 or dpi > 600:
        raise HTTPException(400, "dpi must be between 36 and 600.")
    if not files:
        raise HTTPException(400, "Please upload at least one PDF.")
    if len(files) > P2I_MAX_FILES:
        raise HTTPException(400, f"Up to {P2I_MAX_FILES} PDFs at a time.")

    try:
        excluded = set()
        for token in exclude_pages.split(","):
            if not token.strip():
                continue
            f_idx, _, page_num = token.strip().partition(":")
            excluded.add((int(f_idx), int(page_num)))
    except ValueError:
        raise HTTPException(400, "exclude_pages must be a comma-separated list of fileIndex:page pairs.")

    docs = []
    try:
        for f in files:
            docs.append(await read_pdf_upload(f, P2I_MAX_PDF_BYTES))

        total_page_count = sum(d.page_count for d in docs)
        if total_page_count > P2I_MAX_PAGES:
            raise HTTPException(
                400, f"These PDFs have {total_page_count} pages in total; the limit is {P2I_MAX_PAGES}."
            )

        return _render_pdfs_to_images(files, docs, dpi, output_format, excluded)
    finally:
        for d in docs:
            d.close()


def _render_pdfs_to_images(files, docs, dpi, output_format, excluded):
    zoom = dpi / 72.0

    # Rough output-size estimate before doing any rendering, so an oversized
    # request (many pages x high DPI, especially PNG) fails fast with a
    # useful message instead of spending a minute rendering/encoding and
    # then timing out or blowing past a proxy's response-size limit. PNG
    # stores raw-ish pixels (~3 bytes/px before deflate, deflate barely
    # helps on photo/scan content); JPEG/WEBP land far smaller per pixel.
    total_pixels = sum(
        (p.rect.width * zoom) * (p.rect.height * zoom)
        for f_idx, doc in enumerate(docs)
        for i, p in enumerate(doc, start=1)
        if (f_idx, i) not in excluded
    )
    bytes_per_pixel = 3.0 if output_format == "png" else 0.5
    estimated_bytes = total_pixels * bytes_per_pixel
    if estimated_bytes > MAX_ESTIMATED_OUTPUT_BYTES:
        raise HTTPException(
            400,
            f"This would produce roughly {estimated_bytes / (1024*1024):.0f} MB of images "
            f"at {dpi} DPI ({output_format.upper()}), which is too large to process here. "
            "Try a lower DPI, JPG/WEBP output, or fewer pages.",
        )

    matrix = fitz.Matrix(zoom, zoom)
    pil_format = "JPEG" if output_format in ("jpg", "jpeg") else output_format.upper()
    ext = "jpg" if output_format in ("jpg", "jpeg") else output_format

    # One PDF keeps the flat zip layout; several PDFs each get their own
    # folder so identically-named pages from different files can't collide.
    multi = len(docs) > 1
    base_names = []
    for f in files:
        name = base_name(f.filename)
        candidate, n = name, 2
        while candidate in base_names:
            candidate = f"{name}-{n}"
            n += 1
        base_names.append(candidate)

    pages = []
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f_idx, doc in enumerate(docs):
            name = base_names[f_idx]
            thumb_zoom = min(zoom, THUMB_MAX_WIDTH / doc[0].rect.width)
            thumb_matrix = fitz.Matrix(thumb_zoom, thumb_zoom)
            for i, page in enumerate(doc, start=1):
                if (f_idx, i) in excluded:
                    continue
                pix = page.get_pixmap(matrix=matrix, alpha=(ext == "png"))

                if ext == "png":
                    img_bytes = pix.tobytes("png")
                else:
                    # Convert via Pillow for JPEG/WEBP (pixmap has no alpha in that path)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    img_bytes_io = io.BytesIO()
                    save_kwargs = {"quality": 92} if pil_format == "JPEG" else {}
                    img.save(img_bytes_io, format=pil_format, **save_kwargs)
                    img_bytes = img_bytes_io.getvalue()
                filename = f"{name}-page-{i:02d}.{ext}"
                zf.writestr(f"{name}/{filename}" if multi else filename, img_bytes)

                thumb_pix = page.get_pixmap(matrix=thumb_matrix, alpha=False)
                thumb_img = Image.frombytes("RGB", (thumb_pix.width, thumb_pix.height), thumb_pix.samples)
                thumb_io = io.BytesIO()
                thumb_img.save(thumb_io, format="JPEG", quality=70)
                thumb_data_url = f"data:image/jpeg;base64,{base64.b64encode(thumb_io.getvalue()).decode()}"

                pages.append(
                    {
                        "file_index": f_idx,
                        "page_number": i,
                        "source_filename": files[f_idx].filename,
                        "filename": filename,
                        "width": pix.width,
                        "height": pix.height,
                        "size_bytes": len(img_bytes),
                        "thumb_data_url": thumb_data_url,
                    }
                )

    zip_b64 = base64.b64encode(zip_buffer.getvalue()).decode()

    return JSONResponse(
        {
            "source_filenames": [f.filename for f in files],
            "file_count": len(files),
            "page_count": len(pages),
            "dpi": dpi,
            "format": ext,
            "pages": pages,
            "zip_filename": "pdf-images.zip" if multi else f"{base_names[0]}-images.zip",
            "zip_base64": zip_b64,
        }
    )


@router.post("/images-to-pdf")
async def images_to_pdf(
    files: List[UploadFile] = File(...),
    page_fit: str = Form("fit"),  # "fit" (shrink to page) or "actual" (image size = page size)
):
    if not files:
        raise HTTPException(400, "Please upload at least one image.")
    if len(files) > MAX_PAGES:
        raise HTTPException(400, f"The limit is {MAX_PAGES} images per PDF.")

    images = []
    total_bytes = 0
    for f in files:
        raw = await f.read()
        total_bytes += len(raw)
        if total_bytes > MAX_IMAGE_BYTES * len(files):
            raise HTTPException(413, "Total image payload too large.")
        images.append(flatten_to_rgb(open_image_bytes(raw, f.filename)))

    if not images:
        raise HTTPException(400, "No valid images were provided.")

    pdf_buffer = io.BytesIO()
    first, rest = images[0], images[1:]
    first.save(pdf_buffer, format="PDF", save_all=True, append_images=rest)
    pdf_buffer.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="converted.pdf"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)
