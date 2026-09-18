"""
Contact Sheet — PDF <-> Image conversion + editing API
Endpoints:
  POST /api/pdf-to-images       -> multipart PDF in, JSON (thumbnails + zip) out
  POST /api/images-to-pdf       -> multipart images in, application/pdf out
  POST /api/pdf/combine         -> multipart PDF(s) in, application/pdf out
  POST /api/pdf/inspect         -> multipart PDF(s) in, JSON page thumbnails out (for the page editor)
  POST /api/pdf/build           -> multipart PDF(s) + a page "plan" in, application/pdf out
                                    (drives merge, split/extract, delete pages, reorder, rotate, compress)
  POST /api/pdf/stamp           -> multipart PDF in, application/pdf out
                                    (watermark, page numbers, header/footer text)
  POST /api/pdf/crop-resize     -> multipart PDF in, application/pdf out
                                    (crop margins and optionally normalize page size)
  POST /api/image/compress      -> multipart image(s) in, JSON (compressed results + zip) out
  POST /api/image/remove-bg     -> multipart image(s) in, JSON (cutout PNGs + zip) out
  GET  /api/health              -> liveness check

Background removal runs u2netp directly through onnxruntime (see
BackgroundRemover below) instead of the `rembg` package. `rembg` is fine
for a normal server, but it unconditionally imports pymatting/scipy/
scikit-image at module load time (for an alpha-matting feature we never
use), which alone adds 300+MB of dependencies — enough to blow past
serverless platforms' function-size limits (e.g. Vercel's 250-500MB caps).
Calling onnxruntime directly with the same model and the same pre/post-
processing rembg uses produces byte-identical output without that weight.
"""

import base64
import io
import json
import os
import zipfile
from typing import List

from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
import onnxruntime as ort
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
MAX_PAGES = 400                         # safety cap for JSON+thumbnail payload
MAX_COMBINE_PDFS = 10                    # simple combine flow, in selected order
MAX_BG_REMOVAL_IMAGES = 15              # this one's CPU-heavy, keep batches small

# PDF -> Images has its own input-size limit (20 MB) separate from
# MAX_PDF_BYTES above, which is shared by the merge/build/stamp/crop tools.
P2I_MAX_PDF_BYTES = 20 * 1024 * 1024   # 20 MB
P2I_MAX_PAGES = 400
ALLOWED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_OUTPUT_FORMATS = {"png", "jpg", "jpeg", "webp"}
STAMP_POSITIONS = {
    "top-left", "top-center", "top-right",
    "bottom-left", "bottom-center", "bottom-right",
}
PDF_SIZE_PRESETS = {
    "a4": (595.276, 841.89),
    "letter": (612.0, 792.0),
}

U2NETP_MODEL_PATH = Path(
    os.getenv("U2NETP_MODEL_PATH", str(Path(__file__).parent / "model" / "u2netp.onnx"))
)
U2NETP_DOWNLOAD_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"

_bg_session = None  # lazily created on first use, then reused


def _get_bg_session() -> ort.InferenceSession:
    global _bg_session
    if _bg_session is not None:
        return _bg_session

    if not U2NETP_MODEL_PATH.exists():
        U2NETP_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        import urllib.request

        tmp_path = U2NETP_MODEL_PATH.with_suffix(".onnx.part")
        urllib.request.urlretrieve(U2NETP_DOWNLOAD_URL, tmp_path)
        tmp_path.rename(U2NETP_MODEL_PATH)

    _bg_session = ort.InferenceSession(str(U2NETP_MODEL_PATH), providers=["CPUExecutionProvider"])
    return _bg_session


def _remove_background(img: Image.Image) -> Image.Image:
    """Runs u2netp on `img` and returns an RGBA cutout. Pre/post-processing
    matches rembg's U2netpSession exactly (verified byte-for-byte identical
    output against rembg's own remove())."""
    session = _get_bg_session()
    input_name = session.get_inputs()[0].name

    resized = img.convert("RGB").resize((320, 320), Image.Resampling.LANCZOS)
    arr = np.array(resized)
    arr = arr / max(np.max(arr), 1e-6)
    mean, std = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
    normalized = np.zeros((arr.shape[0], arr.shape[1], 3))
    for c in range(3):
        normalized[:, :, c] = (arr[:, :, c] - mean[c]) / std[c]
    normalized = normalized.transpose((2, 0, 1))
    input_tensor = np.expand_dims(normalized, 0).astype(np.float32)

    outputs = session.run(None, {input_name: input_tensor})
    pred = outputs[0][:, 0, :, :]
    lo, hi = np.min(pred), np.max(pred)
    pred = (pred - lo) / (hi - lo)
    pred = np.squeeze(pred)

    mask = Image.fromarray((pred * 255).astype("uint8"), mode="L")
    mask = mask.resize(img.size, Image.Resampling.LANCZOS)

    rgba = img.convert("RGBA")
    empty = Image.new("RGBA", rgba.size, 0)
    return Image.composite(rgba, empty, mask)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/pdf-to-images")
async def pdf_to_images(
    file: UploadFile = File(...),
    dpi: int = Form(150),
    output_format: str = Form("png"),
    exclude_pages: str = Form(""),  # comma-separated 1-based page numbers to skip entirely
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

    try:
        excluded = {int(n) for n in exclude_pages.split(",") if n.strip()}
    except ValueError:
        raise HTTPException(400, "exclude_pages must be a comma-separated list of page numbers.")

    raw = await file.read()
    if len(raw) > P2I_MAX_PDF_BYTES:
        raise HTTPException(413, "PDF exceeds the 20 MB limit.")

    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise HTTPException(400, "Could not read this PDF — it may be corrupted or encrypted.")

    if doc.page_count == 0:
        raise HTTPException(400, "This PDF has no pages.")
    if doc.page_count > P2I_MAX_PAGES:
        raise HTTPException(
            400, f"This PDF has {doc.page_count} pages; the limit is {P2I_MAX_PAGES}."
        )

    zoom = dpi / 72.0

    # Rough output-size estimate before doing any rendering, so an oversized
    # request (many pages x high DPI, especially PNG) fails fast with a
    # useful message instead of spending a minute rendering/encoding and
    # then timing out or blowing past a proxy's response-size limit. PNG
    # stores raw-ish pixels (~3 bytes/px before deflate, deflate barely
    # helps on photo/scan content); JPEG/WEBP land far smaller per pixel.
    total_pixels = sum(
        (p.rect.width * zoom) * (p.rect.height * zoom)
        for i, p in enumerate(doc, start=1)
        if i not in excluded
    )
    bytes_per_pixel = 3.0 if output_format == "png" else 0.5
    estimated_bytes = total_pixels * bytes_per_pixel
    MAX_ESTIMATED_OUTPUT_BYTES = 200 * 1024 * 1024
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
    mime = f"image/{'jpeg' if ext == 'jpg' else ext}"

    # Full-resolution pages only go into the zip. The JSON response also
    # carries a small on-screen preview per page (capped width, JPEG) instead
    # of the full-res image as a second base64 copy — at 150+ DPI over many
    # pages, embedding every full-res image twice made responses balloon to
    # hundreds of MB and time out (e.g. a 25-page PDF at 150 DPI PNG produced
    # a ~440 MB response). The zip still contains the requested format/DPI
    # untouched; only the preview is downsized.
    THUMB_MAX_WIDTH = 220
    thumb_zoom = min(zoom, THUMB_MAX_WIDTH / doc[0].rect.width)
    thumb_matrix = fitz.Matrix(thumb_zoom, thumb_zoom)

    pages = []
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        base_name = (file.filename or "document").rsplit(".", 1)[0]
        for i, page in enumerate(doc, start=1):
            if i in excluded:
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
            filename = f"{base_name}-page-{i:02d}.{ext}"
            zf.writestr(filename, img_bytes)

            thumb_pix = page.get_pixmap(matrix=thumb_matrix, alpha=False)
            thumb_img = Image.frombytes("RGB", (thumb_pix.width, thumb_pix.height), thumb_pix.samples)
            thumb_io = io.BytesIO()
            thumb_img.save(thumb_io, format="JPEG", quality=70)
            thumb_data_url = f"data:image/jpeg;base64,{base64.b64encode(thumb_io.getvalue()).decode()}"

            pages.append(
                {
                    "filename": filename,
                    "width": pix.width,
                    "height": pix.height,
                    "size_bytes": len(img_bytes),
                    "thumb_data_url": thumb_data_url,
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
        raise HTTPException(400, f"The limit is {MAX_PAGES} images per PDF.")

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


@app.post("/api/pdf/combine")
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
            if not (
                f.content_type in ("application/pdf", "application/x-pdf")
                or (f.filename or "").lower().endswith(".pdf")
            ):
                raise HTTPException(400, f"'{f.filename}' isn't a PDF.")

            raw = await f.read()
            if len(raw) > MAX_PDF_BYTES:
                raise HTTPException(413, f"'{f.filename}' exceeds the 40 MB limit.")

            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                raise HTTPException(400, f"Could not read '{f.filename}' - it may be corrupted or encrypted.")

            if doc.page_count == 0:
                doc.close()
                raise HTTPException(400, f"'{f.filename}' has no pages.")

            total_pages += doc.page_count
            if total_pages > MAX_PAGES:
                doc.close()
                raise HTTPException(400, f"Combined page count exceeds the {MAX_PAGES}-page limit.")

            opened_docs.append(doc)
            out.insert_pdf(doc)

        buf = io.BytesIO()
        out.save(buf, garbage=4, deflate=True)
    finally:
        out.close()
        for doc in opened_docs:
            doc.close()

    buf.seek(0)
    safe_name = (output_filename or "combined.pdf").strip() or "combined.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Output-Pages": str(total_pages),
        "X-Output-Bytes": str(len(buf.getvalue())),
        "Access-Control-Expose-Headers": "X-Output-Pages, X-Output-Bytes",
    }
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


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
            raise HTTPException(400, f"Combined page count exceeds the {MAX_PAGES}-page limit.")

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
        raise HTTPException(400, f"Output would exceed the {MAX_PAGES}-page limit.")
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
        raise HTTPException(400, f"The limit is {MAX_PAGES} images at a time.")
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


@app.post("/api/pdf/stamp")
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
    if not (file.content_type in ("application/pdf", "application/x-pdf") or (file.filename or "").lower().endswith(".pdf")):
        raise HTTPException(400, "Please upload a PDF file.")
    if not any([watermark_text.strip(), page_numbers, header_text.strip(), footer_text.strip()]):
        raise HTTPException(400, "Add a watermark, page numbers, header, or footer — there's nothing to stamp otherwise.")

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
        raise HTTPException(400, f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")

    for pos in (page_number_position, header_position, footer_position):
        if pos not in STAMP_POSITIONS:
            raise HTTPException(400, f"Unknown position '{pos}'.")

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
            x, y, align = _position_point(rect, header_position)
            page.insert_textbox(
                fitz.Rect(rect.x0 + 10, y - 12, rect.x1 - 10, y + 12),
                header_text.strip(),
                fontsize=10,
                color=(0.2, 0.2, 0.2),
                align=align,
                fontname="helv",
            )

        if footer_text.strip():
            x, y, align = _position_point(rect, footer_position)
            page.insert_textbox(
                fitz.Rect(rect.x0 + 10, y - 12, rect.x1 - 10, y + 12),
                footer_text.strip(),
                fontsize=10,
                color=(0.2, 0.2, 0.2),
                align=align,
                fontname="helv",
            )

        if page_numbers:
            label = page_number_format.replace("{n}", str(i)).replace("{total}", str(total))
            x, y, align = _position_point(rect, page_number_position)
            page.insert_textbox(
                fitz.Rect(rect.x0 + 10, y - 12, rect.x1 - 10, y + 12),
                label,
                fontsize=10,
                color=(0.2, 0.2, 0.2),
                align=align,
                fontname="helv",
            )

    buf = io.BytesIO()
    doc.save(buf, garbage=3, deflate=True)
    doc.close()
    buf.seek(0)

    base_name = (file.filename or "document").rsplit(".", 1)[0]
    out_name = f"{base_name}-stamped.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{out_name}"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


@app.post("/api/pdf/crop-resize")
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
    if not (file.content_type in ("application/pdf", "application/x-pdf") or (file.filename or "").lower().endswith(".pdf")):
        raise HTTPException(400, "Please upload a PDF file.")

    page_size = (page_size or "cropped").lower().strip()
    orientation = (orientation or "auto").lower().strip()
    if page_size not in {"cropped", "a4", "letter", "custom"}:
        raise HTTPException(400, "Page size must be cropped, a4, letter, or custom.")
    if orientation not in {"auto", "portrait", "landscape"}:
        raise HTTPException(400, "Orientation must be auto, portrait, or landscape.")
    if min(margin_top, margin_right, margin_bottom, margin_left) < 0:
        raise HTTPException(400, "Crop margins cannot be negative.")

    raw = await file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF exceeds the 40 MB limit.")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise HTTPException(400, "Could not read this PDF â€” it may be corrupted or encrypted.")
    if doc.page_count == 0:
        raise HTTPException(400, "This PDF has no pages.")
    if doc.page_count > MAX_PAGES:
        raise HTTPException(400, f"This PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")

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

    out = fitz.open()
    try:
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

    buf.seek(0)
    base_name = (file.filename or "document").rsplit(".", 1)[0]
    out_name = f"{base_name}-cropped.pdf" if page_size == "cropped" else f"{base_name}-resized.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{out_name}"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


@app.post("/api/image/remove-bg")
async def image_remove_bg(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Please upload at least one image.")
    if len(files) > MAX_BG_REMOVAL_IMAGES:
        raise HTTPException(400, f"Up to {MAX_BG_REMOVAL_IMAGES} images at a time for background removal.")

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

            try:
                cutout = _remove_background(img)
            except Exception:
                raise HTTPException(500, f"Background removal failed for '{f.filename}'.")

            out_io = io.BytesIO()
            cutout.save(out_io, format="PNG")
            out_bytes = out_io.getvalue()

            base_name = (f.filename or "image").rsplit(".", 1)[0]
            out_name = f"{base_name}-nobg.png"
            zf.writestr(out_name, out_bytes)

            results.append(
                {
                    "filename": out_name,
                    "width": cutout.width,
                    "height": cutout.height,
                    "size_bytes": len(out_bytes),
                    "data_url": f"data:image/png;base64,{base64.b64encode(out_bytes).decode()}",
                }
            )

    zip_b64 = base64.b64encode(zip_buffer.getvalue()).decode()
    return JSONResponse(
        {
            "results": results,
            "zip_filename": "no-background.zip",
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
