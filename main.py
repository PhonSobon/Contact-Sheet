"""
Contact Sheet — PDF <-> Image conversion API
Endpoints:
  POST /api/pdf-to-images   -> multipart PDF in, JSON (thumbnails + zip) out
  POST /api/images-to-pdf   -> multipart images in, application/pdf out
  GET  /api/health          -> liveness check
"""

import base64
import io
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


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)