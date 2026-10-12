"""Watermark, page numbers, and header/footer text."""

import io

import fitz  # PyMuPDF
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import MAX_PAGES, MAX_PDF_BYTES, STAMP_POSITIONS
from app.core.pdf_utils import base_name, pdf_response, read_pdf_upload

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

TEXT_COLOR = (0.2, 0.2, 0.2)


def _hex_to_rgb01(hex_color: str):
    h = (hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        h = "808080"
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (0.5, 0.5, 0.5)


def _position_point(rect: "fitz.Rect", position: str, margin: float = 28):
    """Returns (x, y, align) for a given named corner/edge position on a page.
    align: 0=left, 1=center, 2=right (matches fitz.TEXT_ALIGN_* ordering)."""
    x_left, x_center, x_right = rect.x0 + margin, rect.width / 2, rect.x1 - margin
    y_top, y_bottom = rect.y0 + margin, rect.y1 - margin
    mapping = {
        "top-left": (x_left, y_top, 0),
        "top-center": (x_center, y_top, 1),
        "top-right": (x_right, y_top, 2),
        "bottom-left": (x_left, y_bottom, 0),
        "bottom-center": (x_center, y_bottom, 1),
        "bottom-right": (x_right, y_bottom, 2),
    }
    return mapping.get(position, mapping["bottom-center"])


def _insert_line(page: fitz.Page, text: str, position: str) -> None:
    rect = page.rect
    _, y, align = _position_point(rect, position)
    page.insert_textbox(
        fitz.Rect(rect.x0 + 10, y - 12, rect.x1 - 10, y + 12),
        text,
        fontsize=10,
        color=TEXT_COLOR,
        align=align,
        fontname="helv",
    )


@router.post("/stamp")
async def pdf_stamp(
    file: UploadFile = File(...),
    watermark_text: str = Form(""),
    watermark_opacity: float = Form(0.15),
    watermark_size: int = Form(48),
    watermark_rotation: int = Form(45),
    watermark_color: str = Form("808080"),
    page_numbers: bool = Form(False),
    page_number_format: str = Form("Page {n} of {total}"),
    page_number_position: str = Form("bottom-center"),
    header_text: str = Form(""),
    header_position: str = Form("top-center"),
    footer_text: str = Form(""),
    footer_position: str = Form("bottom-center"),
):
    if not any([watermark_text.strip(), page_numbers, header_text.strip(), footer_text.strip()]):
        raise HTTPException(400, "Add a watermark, page numbers, header, or footer — there's nothing to stamp otherwise.")
    for pos in (page_number_position, header_position, footer_position):
        if pos not in STAMP_POSITIONS:
            raise HTTPException(400, f"Unknown position '{pos}'.")

    doc = await read_pdf_upload(file, MAX_PDF_BYTES)
    try:
        if doc.page_count > MAX_PAGES:
            raise HTTPException(400, f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")

        wm_color = _hex_to_rgb01(watermark_color)
        total = doc.page_count

        for i, page in enumerate(doc, start=1):
            rect = page.rect

            if watermark_text.strip():
                cx, cy = rect.width / 2, rect.height / 2
                text = watermark_text.strip()
                # Rough centering: shift left by an estimate of half the text width
                # at this font size so the rotation pivots near the page center.
                approx_half_width = len(text) * watermark_size * 0.28
                mat = fitz.Matrix(1, 1).prerotate(watermark_rotation)
                page.insert_text(
                    fitz.Point(cx - approx_half_width, cy),
                    text,
                    fontsize=watermark_size,
                    color=wm_color,
                    fill_opacity=max(0.02, min(1.0, watermark_opacity)),
                    morph=(fitz.Point(cx, cy), mat),
                    fontname="helv",
                )

            if header_text.strip():
                _insert_line(page, header_text.strip(), header_position)

            if footer_text.strip():
                _insert_line(page, footer_text.strip(), footer_position)

            if page_numbers:
                label = page_number_format.replace("{n}", str(i)).replace("{total}", str(total))
                _insert_line(page, label, page_number_position)

        buf = io.BytesIO()
        doc.save(buf, garbage=3, deflate=True)
    finally:
        doc.close()

    return pdf_response(buf, f"{base_name(file.filename)}-stamped.pdf")
