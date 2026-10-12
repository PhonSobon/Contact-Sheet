"""Crop margins and optionally normalize page size."""

import io

import fitz  # PyMuPDF
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import MAX_PAGES, MAX_PDF_BYTES, PDF_SIZE_PRESETS
from app.core.pdf_utils import base_name, pdf_response, read_pdf_upload

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


def _length_to_points(value: float, unit: str) -> float:
    unit = (unit or "mm").lower().strip()
    if unit == "pt":
        return value
    if unit == "in":
        return value * 72.0
    if unit == "mm":
        return value * 72.0 / 25.4
    raise HTTPException(400, "Unit must be mm, in, or pt.")


def _centered_fit_rect(container: "fitz.Rect", width: float, height: float) -> "fitz.Rect":
    scale = min(container.width / width, container.height / height)
    fitted_w = width * scale
    fitted_h = height * scale
    x0 = container.x0 + (container.width - fitted_w) / 2
    y0 = container.y0 + (container.height - fitted_h) / 2
    return fitz.Rect(x0, y0, x0 + fitted_w, y0 + fitted_h)


@router.post("/crop-resize")
async def pdf_crop_resize(
    file: UploadFile = File(...),
    unit: str = Form("mm"),
    margin_top: float = Form(0),
    margin_right: float = Form(0),
    margin_bottom: float = Form(0),
    margin_left: float = Form(0),
    page_size: str = Form("cropped"),  # "cropped" | "a4" | "letter" | "custom"
    custom_width: float = Form(0),
    custom_height: float = Form(0),
    orientation: str = Form("auto"),  # "auto" | "portrait" | "landscape"
):
    page_size = (page_size or "cropped").lower().strip()
    orientation = (orientation or "auto").lower().strip()
    if page_size not in {"cropped", "a4", "letter", "custom"}:
        raise HTTPException(400, "Page size must be cropped, a4, letter, or custom.")
    if orientation not in {"auto", "portrait", "landscape"}:
        raise HTTPException(400, "Orientation must be auto, portrait, or landscape.")
    if min(margin_top, margin_right, margin_bottom, margin_left) < 0:
        raise HTTPException(400, "Crop margins cannot be negative.")

    top = _length_to_points(margin_top, unit)
    right = _length_to_points(margin_right, unit)
    bottom = _length_to_points(margin_bottom, unit)
    left = _length_to_points(margin_left, unit)

    if page_size == "custom":
        if custom_width <= 0 or custom_height <= 0:
            raise HTTPException(400, "Custom width and height must be greater than zero.")
        preset_size = (_length_to_points(custom_width, unit), _length_to_points(custom_height, unit))
    elif page_size in PDF_SIZE_PRESETS:
        preset_size = PDF_SIZE_PRESETS[page_size]
    else:
        preset_size = None

    doc = await read_pdf_upload(file, MAX_PDF_BYTES)
    out = fitz.open()
    try:
        if doc.page_count > MAX_PAGES:
            raise HTTPException(400, f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")

        for page_index, page in enumerate(doc):
            rect = page.rect
            clip = fitz.Rect(rect.x0 + left, rect.y0 + top, rect.x1 - right, rect.y1 - bottom)
            if clip.width < 12 or clip.height < 12:
                raise HTTPException(400, f"Crop margins remove too much of page {page_index + 1}.")

            if preset_size:
                page_w, page_h = preset_size
                if orientation == "landscape" or (orientation == "auto" and clip.width > clip.height):
                    page_w, page_h = max(page_w, page_h), min(page_w, page_h)
                elif orientation == "portrait" or orientation == "auto":
                    page_w, page_h = min(page_w, page_h), max(page_w, page_h)
            else:
                page_w, page_h = clip.width, clip.height

            new_page = out.new_page(width=page_w, height=page_h)
            target = fitz.Rect(0, 0, page_w, page_h)
            if preset_size:
                target = _centered_fit_rect(target, clip.width, clip.height)
            new_page.show_pdf_page(target, doc, page_index, clip=clip, keep_proportion=True)

        buf = io.BytesIO()
        out.save(buf, garbage=4, deflate=True)
    finally:
        out.close()
        doc.close()

    suffix = "cropped" if page_size == "cropped" else "resized"
    return pdf_response(buf, f"{base_name(file.filename)}-{suffix}.pdf")
