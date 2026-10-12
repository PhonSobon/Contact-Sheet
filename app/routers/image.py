"""Image compression and background removal."""

import base64
import io
import zipfile
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from app.core.config import ALLOWED_OUTPUT_FORMATS, MAX_BG_REMOVAL_IMAGES, MAX_IMAGE_BYTES, MAX_PAGES
from app.core.image_utils import flatten_to_rgb, read_image_upload
from app.services.background_removal import remove_background

router = APIRouter(prefix="/api/image", tags=["image"])


@router.post("/compress")
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
            img, raw = await read_image_upload(f, MAX_IMAGE_BYTES)
            original_bytes = len(raw)

            if ext == "jpg":
                img = flatten_to_rgb(img)

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


@router.post("/remove-bg")
async def image_remove_bg(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Please upload at least one image.")
    if len(files) > MAX_BG_REMOVAL_IMAGES:
        raise HTTPException(400, f"Up to {MAX_BG_REMOVAL_IMAGES} images at a time for background removal.")

    results = []
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            img, _ = await read_image_upload(f, MAX_IMAGE_BYTES)

            try:
                cutout = remove_background(img)
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
