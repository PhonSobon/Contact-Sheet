"""
Contact Sheet — PDF <-> Image conversion + editing API
Endpoints:
  POST /api/pdf-to-images   -> multipart PDF in, JSON (thumbnails + zip) out
  POST /api/images-to-pdf   -> multipart images in, application/pdf out
  POST /api/pdf/inspect     -> multipart PDF(s) in, JSON page thumbnails out (for the page editor)
  POST /api/pdf/build       -> multipart PDF(s) + a page "plan" in, application/pdf out
                                (drives merge, split/extract, delete pages, reorder, rotate, compress)
  POST /api/image/compress  -> multipart image(s) in, JSON (compressed results + zip) out
  GET  /api/health          -> liveness check
"""

import base64
import io
import json
import zipfile
from typing import List

from pathlib import Path

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

app = FastAPI(title="Contact Sheet", version="1.0.0")

# CORS is only needed if you ever split the frontend onto another origin.
# Same-origin (this file serving both API + page) doesn't need it, but it's
# harmless to leave open here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"

MAX_PDF_BYTES = 40 * 1024 * 1024       # 40 MB
MAX_IMAGE_BYTES = 20 * 1024 * 1024     # 20 MB per image
MAX_PAGES = 60                          # safety cap for JSON+thumbnail payload
ALLOWED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_OUTPUT_FORMATS = {"png", "jpg", "jpeg", "webp"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/pdf-to-images")
async def pdf_to_images(
    file: UploadFile = File(...),
    dpi: int = Form(150),
    output_format: str = Form("png"),
):
    output_format = output_format.lower().strip()
    if output_format not in ALLOWED_OUTPUT_FORMATS:
        raise HTTPException(400, f"Unsupported output format '{output_format}'.")
    if dpi < 36 or dpi > 600:
        raise HTTPException(400, "dpi must be between 36 and 600.")
    if file.content_type not in ("application/pdf", "application/x-pdf") and not (
        file.filename or ""
    ).lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")

    raw = await file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF exceeds the 40 MB limit.")

    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise HTTPException(400, "Could not read this PDF — it may be corrupted or encrypted.")

    if doc.page_count == 0:
        raise HTTPException(400, "This PDF has no pages.")
    if doc.page_count > MAX_PAGES:
        raise HTTPException(
            400, f"This PDF has {doc.page_count} pages; the demo limit is {MAX_PAGES}."
        )

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pil_format = "JPEG" if output_format in ("jpg", "jpeg") else output_format.upper()
    ext = "jpg" if output_format in ("jpg", "jpeg") else output_format
    mime = f"image/{'jpeg' if ext == 'jpg' else ext}"

    pages = []
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        base_name = (file.filename or "document").rsplit(".", 1)[0]
        for i, page in enumerate(doc, start=1):
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
            filename = f"{base_name}-page-{i:02d}.{ext}"
            zf.writestr(filename, img_bytes)

            pages.append(
                {
                    "filename": filename,
                    "width": pix.width,
                    "height": pix.height,
                    "size_bytes": len(img_bytes),
                    "data_url": f"data:{mime};base64,{base64.b64encode(img_bytes).decode()}",
                }
            )

    doc.close()
    zip_b64 = base64.b64encode(zip_buffer.getvalue()).decode()

    return JSONResponse(
        {
            "source_filename": file.filename,
            "page_count": len(pages),
            "dpi": dpi,
            "format": ext,
            "pages": pages,
            "zip_filename": f"{base_name}-images.zip",
            "zip_base64": zip_b64,
        }
    )


@app.post("/api/images-to-pdf")
async def images_to_pdf(
    files: List[UploadFile] = File(...),
    page_fit: str = Form("fit"),  # "fit" (shrink to page) or "actual" (image size = page size)
):
    if not files:
        raise HTTPException(400, "Please upload at least one image.")
    if len(files) > MAX_PAGES:
        raise HTTPException(400, f"The demo limit is {MAX_PAGES} images per PDF.")

    images = []
    total_bytes = 0
    for f in files:
        raw = await f.read()
        total_bytes += len(raw)
        if total_bytes > MAX_IMAGE_BYTES * len(files):
            raise HTTPException(413, "Total image payload too large.")
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            raise HTTPException(400, f"'{f.filename}' isn't a readable image.")

        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
        images.append(img)

    if not images:
        raise HTTPException(400, "No valid images were provided.")

    pdf_buffer = io.BytesIO()
    first, rest = images[0], images[1:]
    first.save(pdf_buffer, format="PDF", save_all=True, append_images=rest)
    pdf_buffer.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="converted.pdf"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.post("/api/pdf/inspect")
async def pdf_inspect(
    files: List[UploadFile] = File(...),
    thumb_dpi: int = Form(90),
):
    """Render low-res thumbnails for every page of every uploaded PDF, keyed by
    source_index so the frontend can build an editable page grid — and merge,
    since dropping multiple PDFs here just interleaves their pages."""
    if not files:
        raise HTTPException(400, "Please upload at least one PDF.")
    if len(files) > 10:
        raise HTTPException(400, "Up to 10 PDFs at a time.")

    sources = []
    total_pages = 0
    for src_idx, f in enumerate(files):
        if not (f.content_type in ("application/pdf", "application/x-pdf") or (f.filename or "").lower().endswith(".pdf")):
            raise HTTPException(400, f"'{f.filename}' isn't a PDF.")
        raw = await f.read()
        if len(raw) > MAX_PDF_BYTES:
            raise HTTPException(413, f"'{f.filename}' exceeds the 40 MB limit.")
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
        except Exception:
            raise HTTPException(400, f"Could not read '{f.filename}' — it may be corrupted or encrypted.")
        if doc.page_count == 0:
            raise HTTPException(400, f"'{f.filename}' has no pages.")

        total_pages += doc.page_count
        if total_pages > MAX_PAGES:
            raise HTTPException(400, f"Combined page count exceeds the {MAX_PAGES}-page demo limit.")

        zoom = max(24, min(200, thumb_dpi)) / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pages = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_bytes = pix.tobytes("png")
            pages.append(
                {
                    "page_index": i,
                    "width": pix.width,
                    "height": pix.height,
                    "rotation": page.rotation,
                    "data_url": f"data:image/png;base64,{base64.b64encode(img_bytes).decode()}",
                }
            )
        doc.close()
        sources.append(
            {
                "source_index": src_idx,
                "filename": f.filename,
                "page_count": len(pages),
                "pages": pages,
            }
        )

    return JSONResponse({"sources": sources})


@app.post("/api/pdf/build")
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
        raise HTTPException(400, f"Output would exceed the {MAX_PAGES}-page demo limit.")
    if compress not in ("none", "optimize", "rasterize"):
        raise HTTPException(400, "Unknown compress mode.")

    docs = {}
    for idx, f in enumerate(files):
        raw = await f.read()
        if len(raw) > MAX_PDF_BYTES:
            raise HTTPException(413, f"'{f.filename}' exceeds the 40 MB limit.")
        try:
            docs[idx] = fitz.open(stream=raw, filetype="pdf")
        except Exception:
            raise HTTPException(400, f"Could not read '{f.filename}'.")

    out = fitz.open()
    try:
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
            # Biggest size win — flattens each page to a JPEG, so any real
            # text becomes unselectable. Good for photo-heavy/scanned PDFs.
            zoom = max(36, min(300, raster_dpi)) / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            raster_doc = fitz.open()
            for page in out:
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                jpg_io = io.BytesIO()
                img.save(jpg_io, format="JPEG", quality=max(1, min(95, raster_quality)))
                jpg_bytes = jpg_io.getvalue()
                page_w = pix.width * 72.0 / raster_dpi
                page_h = pix.height * 72.0 / raster_dpi
                new_page = raster_doc.new_page(width=page_w, height=page_h)
                new_page.insert_image(fitz.Rect(0, 0, page_w, page_h), stream=jpg_bytes)
            raster_doc.save(buf, garbage=4, deflate=True)
            raster_doc.close()
        else:
            out.save(buf, garbage=4, deflate=True, deflate_images=(compress == "optimize"))
    finally:
        out.close()
        for d in docs.values():
            d.close()

    buf.seek(0)
    size = len(buf.getvalue())
    safe_name = (output_filename or "edited.pdf").strip() or "edited.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Output-Bytes": str(size),
        "Access-Control-Expose-Headers": "X-Output-Bytes",
    }
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


@app.post("/api/image/compress")
async def image_compress(
    files: List[UploadFile] = File(...),
    quality: int = Form(75),
    max_dimension: int = Form(0),  # 0 = keep original dimensions
    output_format: str = Form("jpg"),
):
    if not files:
        raise HTTPException(400, "Please upload at least one image.")
    if len(files) > MAX_PAGES:
        raise HTTPException(400, f"The demo limit is {MAX_PAGES} images at a time.")
    output_format = output_format.lower().strip()
    if output_format not in ALLOWED_OUTPUT_FORMATS:
        raise HTTPException(400, f"Unsupported output format '{output_format}'.")
    quality = max(1, min(95, quality))
    ext = "jpg" if output_format in ("jpg", "jpeg") else output_format
    pil_format = "JPEG" if ext == "jpg" else output_format.upper()

    results = []
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            raw = await f.read()
            if len(raw) > MAX_IMAGE_BYTES:
                raise HTTPException(413, f"'{f.filename}' exceeds the 20 MB limit.")
            try:
                img = Image.open(io.BytesIO(raw))
                img.load()
            except Exception:
                raise HTTPException(400, f"'{f.filename}' isn't a readable image.")
            original_bytes = len(raw)

            if ext == "jpg":
                if img.mode in ("RGBA", "P", "LA"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    rgba = img.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[-1])
                    img = bg
                else:
                    img = img.convert("RGB")

            if max_dimension and max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
                img = img.resize(new_size, Image.LANCZOS)

            out_io = io.BytesIO()
            if pil_format == "JPEG":
                img.save(out_io, format="JPEG", quality=quality, optimize=True)
            elif pil_format == "WEBP":
                img.save(out_io, format="WEBP", quality=quality, method=6)
            else:
                img.save(out_io, format=pil_format, optimize=True)
            out_bytes = out_io.getvalue()

            base_name = (f.filename or "image").rsplit(".", 1)[0]
            out_name = f"{base_name}-compressed.{ext}"
            zf.writestr(out_name, out_bytes)

            mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
            results.append(
                {
                    "filename": out_name,
                    "original_bytes": original_bytes,
                    "compressed_bytes": len(out_bytes),
                    "width": img.width,
                    "height": img.height,
                    "data_url": f"data:{mime};base64,{base64.b64encode(out_bytes).decode()}",
                }
            )

    zip_b64 = base64.b64encode(zip_buffer.getvalue()).decode()
    return JSONResponse(
        {
            "results": results,
            "zip_filename": "compressed-images.zip",
            "zip_base64": zip_b64,
        }
    )


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# Any other static assets (css/js/images) placed in static/ are served as-is,
# e.g. static/foo.png -> /foo.png. Mounted last so it never shadows /api/*.
app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)