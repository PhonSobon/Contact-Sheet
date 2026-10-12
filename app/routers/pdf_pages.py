"""Remove pages from a PDF in place."""

import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import MAX_PDF_BYTES
from app.core.pdf_utils import base_name, parse_page_ranges, pdf_response, read_pdf_upload

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


@router.post("/remove-pages")
async def pdf_remove_pages(
    file: UploadFile = File(...),
    pages: str = Form(...),  # 1-based pages/ranges to remove, e.g. "2, 5-7"
):
    """Delete pages from a PDF without touching anything else. Unlike
    /api/pdf/build (which copies pages into a fresh document), this edits the
    original document in place, so images, fonts, links, bookmarks, form
    fields and metadata are kept exactly as they were — nothing is
    re-rendered or re-compressed. garbage=1 only drops objects that belonged
    solely to the removed pages."""
    doc = await read_pdf_upload(file, MAX_PDF_BYTES)
    try:
        to_remove = parse_page_ranges(pages, doc.page_count)
        if not to_remove:
            raise HTTPException(400, "Choose at least one page to remove.")
        keep = [i for i in range(doc.page_count) if i not in to_remove]
        if not keep:
            raise HTTPException(400, "You can't remove every page — at least one must remain.")

        doc.select(keep)
        buf = io.BytesIO()
        doc.save(buf, garbage=1)
    finally:
        doc.close()

    return pdf_response(
        buf,
        f"{base_name(file.filename)}-pages-removed.pdf",
        {
            "X-Output-Pages": str(len(keep)),
            "X-Removed-Pages": str(len(to_remove)),
            "X-Output-Bytes": str(len(buf.getvalue())),
        },
    )
