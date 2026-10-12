"""Detect and remove watermarks."""

import io
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import MAX_PAGES, MAX_PDF_BYTES
from app.core.pdf_utils import base_name, pdf_response, read_pdf_upload
from app.services import image_watermark, watermark

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

MAX_WATERMARK_TEXTS = 10


@router.post("/watermark/detect")
async def pdf_watermark_detect(file: UploadFile = File(...)):
    """Lists what looks like a watermark, so the user can choose what to remove."""
    doc = await read_pdf_upload(file, MAX_PDF_BYTES)
    try:
        if doc.page_count > MAX_PAGES:
            raise HTTPException(400, f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")
        return JSONResponse(watermark.detect(doc))
    finally:
        doc.close()


@router.post("/remove-watermark")
async def pdf_remove_watermark(
    file: UploadFile = File(...),
    texts: str = Form("[]"),           # JSON list of watermark texts, e.g. ["CONFIDENTIAL"]
    remove_stamps: bool = Form(False),  # also delete stamp annotations ("Draft", "Approved"...)
    # Scanned pages: clean the page images themselves.
    images_light: bool = Form(False),
    images_light_strength: int = Form(50),
    images_color: str = Form(""),
    images_tolerance: int = Form(30),
):
    try:
        text_list = json.loads(texts or "[]")
    except ValueError:
        raise HTTPException(400, "texts must be a JSON list of strings.")
    if not isinstance(text_list, list) or not all(isinstance(t, str) for t in text_list):
        raise HTTPException(400, "texts must be a JSON list of strings.")
    text_list = [t.strip() for t in text_list if t.strip()][:MAX_WATERMARK_TEXTS]
    try:
        # Page images are always filled with the paper colour: blending would
        # smear the scanned text that sits next to the watermark.
        image_options = image_watermark.parse_options(
            images_light, images_light_strength, images_color, images_tolerance, "paper"
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    doc = await read_pdf_upload(file, MAX_PDF_BYTES)
    try:
        if doc.page_count > MAX_PAGES:
            raise HTTPException(400, f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")
        report = watermark.remove(doc, text_list, remove_stamps=remove_stamps)
        cleaned_images = image_watermark.clean_pdf_images(doc, image_options)
        if report.total + cleaned_images == 0:
            hint = (
                " Check the spelling of the watermark text."
                if text_list
                else " Type the watermark text (for example CONFIDENTIAL) and try again."
            )
            raise HTTPException(
                422,
                "No removable watermark was found." + hint
                + " If the watermark is part of a scanned page, turn on the scanned-page cleanup.",
            )
        buf = io.BytesIO()
        doc.save(buf, garbage=3, deflate=True)
    finally:
        doc.close()

    return pdf_response(
        buf,
        f"{base_name(file.filename)}-no-watermark.pdf",
        {
            "X-Removed-Text": str(report.text_objects),
            "X-Removed-Marked": str(report.marked_sections),
            "X-Removed-Annotations": str(report.annotations),
            "X-Removed-XObjects": str(report.xobjects),
            "X-Cleaned-Images": str(cleaned_images),
            "X-Output-Bytes": str(len(buf.getvalue())),
        },
    )
