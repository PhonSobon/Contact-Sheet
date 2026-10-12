"""Remove watermarks from images."""

import base64
import io
import re
import zipfile
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from app.core.config import MAX_IMAGE_BYTES
from app.core.image_utils import open_image_bytes, read_image_upload
from app.services import image_watermark

router = APIRouter(prefix="/api/image", tags=["image"])

MAX_WATERMARK_IMAGES = 10
OUTPUT_FORMATS = {"same", "png", "jpg", "webp"}
PIL_FORMATS = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}


def _output_ext(requested: str, source: Image.Image) -> str:
    if requested != "same":
        return requested
    return {"JPEG": "jpg", "WEBP": "webp"}.get(source.format or "", "png")


@router.post("/remove-watermark")
async def image_remove_watermark(
    files: List[UploadFile] = File(...),
    # Optional painted masks: white = watermark. Named "mask-<index>.png" to
    # match files[index]; images without a painted mask simply send none.
    masks: List[UploadFile] = File(default=[]),
    light: bool = Form(False),          # fade pale watermarks on documents
    light_strength: int = Form(50),     # 0-100
    color: str = Form(""),              # hex colour picked from the watermark
    tolerance: int = Form(30),          # 0-100
    fill: str = Form("auto"),           # auto | blend | paper
    output_format: str = Form("same"),  # same | png | jpg | webp
):
    if not files:
        raise HTTPException(400, "Please upload at least one image.")
    if len(files) > MAX_WATERMARK_IMAGES:
        raise HTTPException(400, f"Up to {MAX_WATERMARK_IMAGES} images at a time.")
    if output_format not in OUTPUT_FORMATS:
        raise HTTPException(400, f"Unsupported output format '{output_format}'.")
    try:
        options = image_watermark.parse_options(light, light_strength, color, tolerance, fill)
    except ValueError as e:
        raise HTTPException(400, str(e))

    mask_by_index = {}
    for m in masks:
        found = re.fullmatch(r"mask-(\d+)\.png", m.filename or "")
        if not found:
            raise HTTPException(400, "Masks must be named mask-<index>.png.")
        mask_by_index[int(found.group(1))] = open_image_bytes(await m.read(), m.filename)

    results = []
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, f in enumerate(files):
            img, _ = await read_image_upload(f, MAX_IMAGE_BYTES)
            if img.width * img.height > image_watermark.MAX_PIXELS:
                raise HTTPException(400, f"'{f.filename}' is too large ({img.width}×{img.height}); the limit is about 30 megapixels.")
            mask = mask_by_index.get(idx)
            if mask is None and options["light_strength"] is None and options["color"] is None:
                raise HTTPException(
                    400,
                    f"Nothing to remove in '{f.filename}': paint over the watermark, "
                    "or turn on Light watermark or By colour.",
                )

            cleaned, stats = image_watermark.clean_image(img, mask=mask, **options)
            if not (stats["painted_px"] or stats["light_px"] or stats["color_px"]):
                raise HTTPException(
                    422,
                    f"No watermark pixels were found in '{f.filename}'. Try a higher strength or tolerance, "
                    "pick the colour again, or paint over the watermark.",
                )

            ext = _output_ext(output_format, img)
            pil_format = PIL_FORMATS[ext]
            if pil_format == "JPEG" and cleaned.mode != "RGB":
                cleaned = cleaned.convert("RGB")
            out_io = io.BytesIO()
            save_kwargs = {"quality": 95} if pil_format in ("JPEG", "WEBP") else {"optimize": True}
            cleaned.save(out_io, format=pil_format, **save_kwargs)
            out_bytes = out_io.getvalue()

            out_name = f"{(f.filename or 'image').rsplit('.', 1)[0]}-no-watermark.{ext}"
            zf.writestr(out_name, out_bytes)
            mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
            results.append(
                {
                    "index": idx,
                    "filename": out_name,
                    "width": cleaned.width,
                    "height": cleaned.height,
                    "size_bytes": len(out_bytes),
                    "stats": stats,
                    "data_url": f"data:{mime};base64,{base64.b64encode(out_bytes).decode()}",
                }
            )

    return JSONResponse(
        {
            "results": results,
            "zip_filename": "no-watermark-images.zip",
            "zip_base64": base64.b64encode(zip_buffer.getvalue()).decode(),
        }
    )
