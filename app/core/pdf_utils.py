"""Shared helpers for reading uploaded PDFs and building PDF responses."""

import io

import fitz  # PyMuPDF
from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse

PDF_CONTENT_TYPES = ("application/pdf", "application/x-pdf")


def is_pdf_upload(f: UploadFile) -> bool:
    return f.content_type in PDF_CONTENT_TYPES or (f.filename or "").lower().endswith(".pdf")


def open_pdf_bytes(raw: bytes, filename: str) -> fitz.Document:
    """Opens PDF bytes, raising a clear 400 for corrupted or password-protected files."""
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise HTTPException(400, f"Could not read '{filename}' — it may be corrupted or not a real PDF.")
    # PyMuPDF already tries an empty password; needs_pass still being set
    # means the file has a real open password. Touching its pages would crash.
    if doc.needs_pass:
        doc.close()
        raise HTTPException(
            400, f"'{filename}' is password-protected. Remove the password (unlock it) and try again."
        )
    if doc.page_count == 0:
        doc.close()
        raise HTTPException(400, f"'{filename}' has no pages.")
    return doc


async def read_pdf_upload(f: UploadFile, max_bytes: int) -> fitz.Document:
    """Validates type and size of an uploaded PDF, then opens it."""
    if not is_pdf_upload(f):
        raise HTTPException(400, f"'{f.filename}' isn't a PDF.")
    raw = await f.read()
    if len(raw) > max_bytes:
        raise HTTPException(413, f"'{f.filename}' exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    return open_pdf_bytes(raw, f.filename or "document.pdf")


def ensure_pdf_name(name: str, default: str) -> str:
    safe_name = (name or default).strip() or default
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    return safe_name


def base_name(filename: str, default: str = "document") -> str:
    return (filename or default).rsplit(".", 1)[0] or default


def pdf_response(buf: io.BytesIO, filename: str, extra_headers: dict = None) -> StreamingResponse:
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if extra_headers:
        headers.update(extra_headers)
        headers["Access-Control-Expose-Headers"] = ", ".join(extra_headers)
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


def parse_page_ranges(spec: str, page_count: int) -> set:
    """Parses '1, 3, 5-7' (1-based, inclusive) into a set of 0-based page indexes."""
    pages = set()
    for token in (spec or "").replace(" ", "").split(","):
        if not token:
            continue
        start, sep, end = token.partition("-")
        try:
            lo = int(start)
            hi = int(end) if sep else lo
        except ValueError:
            raise HTTPException(400, f"'{token}' isn't a valid page or range.")
        if lo > hi:
            lo, hi = hi, lo
        if lo < 1 or hi > page_count:
            raise HTTPException(400, f"Page '{token}' is out of range — this PDF has {page_count} pages.")
        pages.update(range(lo - 1, hi))
    return pages
