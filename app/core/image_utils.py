"""Shared helpers for reading uploaded images."""

import io

from fastapi import HTTPException, UploadFile
from PIL import Image


def open_image_bytes(raw: bytes, filename: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(400, f"'{filename}' isn't a readable image.")
    return img


async def read_image_upload(f: UploadFile, max_bytes: int) -> tuple:
    """Returns (image, raw_bytes) after checking the size limit."""
    raw = await f.read()
    if len(raw) > max_bytes:
        raise HTTPException(413, f"'{f.filename}' exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    return open_image_bytes(raw, f.filename), raw


def flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Composites transparent images onto white so they can be saved as JPEG/PDF."""
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img.convert("RGB")
