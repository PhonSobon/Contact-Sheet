"""
Image watermark removal in plain numpy (no OpenCV, to keep deploys small).

Three tools, usable together:
  * inpaint(img, mask): fills the masked pixels from their surroundings with a
    multi-scale harmonic fill — coarse levels carry colour across big holes,
    fine levels restore detail at the edges. Works well for text and logo
    watermarks on smooth or gently varying backgrounds.
  * light_watermark_mask(img, strength): pale, low-contrast pixels — the
    typical grey/coloured watermark on a scanned document — which are then
    pushed to the paper colour, keeping dark text untouched.
  * color_mask(img, rgb, tolerance): pixels close to a picked colour.
"""

import io
from typing import Optional, Tuple

import numpy as np
from PIL import Image

MAX_PIXELS = 30_000_000  # ~30 MP; larger images are refused before any work


def _shift_mean(a: np.ndarray) -> np.ndarray:
    """Mean of the 4 neighbours, edges replicated. Works on HxW or HxWxC."""
    p = np.pad(a, ((1, 1), (1, 1)) + ((0, 0),) * (a.ndim - 2), mode="edge")
    return (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) * 0.25


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(max(0, radius)):
        p = np.pad(out, 1, mode="constant")
        out = out | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return out


def _downsample(img: np.ndarray, known: np.ndarray):
    """2x downsample that averages only known pixels, so the hole doesn't
    bleed its (watermarked) colour into the coarse level."""
    h, w = known.shape
    h2, w2 = (h + 1) // 2, (w + 1) // 2
    img = np.pad(img, ((0, h2 * 2 - h), (0, w2 * 2 - w), (0, 0)), mode="edge")
    k = np.pad(known, ((0, h2 * 2 - h), (0, w2 * 2 - w)), mode="edge").astype(np.float32)
    ks = k.reshape(h2, 2, w2, 2).sum(axis=(1, 3))
    s = (img * k[..., None]).reshape(h2, 2, w2, 2, -1).sum(axis=(1, 3))
    out = np.where(ks[..., None] > 0, s / np.maximum(ks, 1)[..., None], 0)
    return out.astype(np.float32), ks > 0


def _harmonic_fill(img: np.ndarray, hole: np.ndarray, iterations: int) -> np.ndarray:
    for _ in range(iterations):
        img[hole] = _shift_mean(img)[hole]
    return img


def inpaint(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """img: HxWx3 uint8, mask: HxW bool (True = remove). Returns uint8."""
    if not mask.any():
        return img
    ys, xs = np.nonzero(mask)
    pad = 24
    y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + pad + 1)

    work = img[y0:y1, x0:x1].astype(np.float32)
    hole = mask[y0:y1, x0:x1]

    # Pyramid of (image, known) pairs, finest first.
    levels = [(work, ~hole)]
    while min(levels[-1][1].shape) > 24 and (~levels[-1][1]).any():
        levels.append(_downsample(*levels[-1]))

    coarse, known = levels[-1]
    if known.any():
        coarse[~known] = coarse[known].mean(axis=0)
    filled = _harmonic_fill(coarse, ~known, 150)

    for depth in range(len(levels) - 2, -1, -1):
        level_img, level_known = levels[depth]
        h, w = level_known.shape
        up = np.repeat(np.repeat(filled, 2, axis=0), 2, axis=1)[:h, :w]
        level_img = level_img.copy()
        level_img[~level_known] = up[~level_known]
        filled = _harmonic_fill(level_img, ~level_known, 40 if depth == 0 else 60)

    out = img.copy()
    region = out[y0:y1, x0:x1]
    region[hole] = np.clip(filled[hole] + 0.5, 0, 255).astype(np.uint8)
    return out


def _luminance(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


def paper_color(img: np.ndarray) -> np.ndarray:
    """The page background: the median colour of the brightest pixels."""
    lum = _luminance(img.astype(np.float32))
    bright = img[lum >= np.percentile(lum, 90)]
    return np.median(bright, axis=0) if len(bright) else np.array([255, 255, 255], np.float32)


def looks_like_document(img: np.ndarray) -> bool:
    """Mostly flat, pale, unsaturated background — a page, not a photo."""
    small = img[:: max(1, img.shape[0] // 300), :: max(1, img.shape[1] // 300)].astype(np.float32)
    lum = _luminance(small)
    paper_lum = float(_luminance(paper_color(small)[None, None, :])[0, 0])
    sat = small.max(axis=-1) - small.min(axis=-1)
    return paper_lum > 170 and float(((np.abs(lum - paper_lum) < 25) & (sat < 40)).mean()) > 0.55


def remove_light_watermark(img: np.ndarray, strength: int) -> Tuple[np.ndarray, int]:
    """Pushes pale pixels to the paper colour. strength 0-100: higher removes
    darker watermarks too (and risks fading light-grey text). Pixels between
    the cut-off and slightly darker are blended, so text edges stay smooth."""
    strength = max(0, min(100, strength))
    f = img.astype(np.float32)
    lum = _luminance(f)
    paper = paper_color(img).astype(np.float32)
    paper_lum = float(_luminance(paper[None, None, :])[0, 0])

    cutoff = paper_lum - 18 - strength * 1.1   # strength 50 -> ~70 below paper
    ramp = 28.0
    weight = np.clip((lum - (cutoff - ramp)) / ramp, 0, 1)[..., None]
    out = f * (1 - weight) + paper * weight
    changed = int(((weight[..., 0] > 0.5) & (lum < paper_lum - 6)).sum())
    return np.clip(out + 0.5, 0, 255).astype(np.uint8), changed


def color_mask(img: np.ndarray, rgb: Tuple[int, int, int], tolerance: int) -> np.ndarray:
    """Pixels within `tolerance` (0-100) of the picked colour."""
    diff = img.astype(np.int32) - np.array(rgb, np.int32)
    dist = np.sqrt((diff ** 2).sum(axis=-1))
    return dist <= 8 + tolerance * 2.2   # 0 -> exact-ish, 100 -> very loose


def parse_hex(color: str) -> Optional[Tuple[int, int, int]]:
    h = (color or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def clean_image(
    img: Image.Image,
    mask: Optional[Image.Image] = None,
    light_strength: Optional[int] = None,
    color: Optional[Tuple[int, int, int]] = None,
    tolerance: int = 30,
    grow: int = 2,
    fill: str = "auto",
) -> Tuple[Image.Image, dict]:
    """Runs the chosen steps; returns the cleaned image and what was changed.
    fill: how removed areas are filled — "blend" (from the surroundings, best
    for photos), "paper" (the page colour, best for documents: blending would
    smear nearby text into the hole) or "auto" (picks one). Transparency is
    preserved."""
    alpha = img.getchannel("A") if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info) else None
    arr = np.array(img.convert("RGB"))
    stats = {"painted_px": 0, "light_px": 0, "color_px": 0}

    hole = np.zeros(arr.shape[:2], bool)
    if mask is not None:
        m = np.array(mask.convert("L").resize(img.size, Image.Resampling.NEAREST)) > 127
        stats["painted_px"] = int(m.sum())
        hole |= m
    if color is not None:
        cm = color_mask(arr, color, tolerance)
        stats["color_px"] = int(cm.sum())
        hole |= cm
    if hole.any():
        # Watermark edges are anti-aliased; grow the hole a little so no halo stays.
        hole = dilate(hole, grow)
        use_paper = fill == "paper" or (fill == "auto" and looks_like_document(arr))
        stats["fill"] = "paper" if use_paper else "blend"
        if use_paper:
            arr = arr.copy()
            arr[hole] = paper_color(arr).astype(np.uint8)
        else:
            arr = inpaint(arr, hole)

    if light_strength is not None:
        arr, stats["light_px"] = remove_light_watermark(arr, light_strength)

    out = Image.fromarray(arr, "RGB")
    if alpha is not None:
        out.putalpha(alpha)
    return out, stats


FILL_MODES = {"auto", "blend", "paper"}


def parse_options(light: bool, light_strength: int, color: str, tolerance: int, fill: str) -> dict:
    """Validates the user's cleanup choices (shared by the image and PDF tools).
    Raises ValueError with a message meant for the user."""
    picked = None
    if (color or "").strip():
        picked = parse_hex(color)
        if picked is None:
            raise ValueError("The picked colour must look like #c81e28.")
    if fill not in FILL_MODES:
        raise ValueError("Fill must be auto, blend or paper.")
    return {
        "light_strength": max(0, min(100, light_strength)) if light else None,
        "color": picked,
        "tolerance": max(0, min(100, tolerance)),
        "fill": fill,
    }


MIN_PDF_IMAGE_PIXELS = 40_000  # skip icons/bullets; scans and photos are far larger


def clean_pdf_images(doc, options: dict) -> int:
    """Applies the light/colour cleanup to the images inside a PDF (scanned
    pages). Each image is replaced in place, so the text layer, links and
    everything else stay as they are. Returns how many images changed."""
    import fitz  # PyMuPDF; imported here so the image tool doesn't need it

    if options["light_strength"] is None and options["color"] is None:
        return 0
    done, changed = set(), 0
    for page in doc:
        for info in page.get_images(full=True):
            xref, smask = info[0], info[1]
            if xref in done or smask:  # images with a soft mask: leave alone
                continue
            done.add(xref)
            pix = fitz.Pixmap(doc, xref)
            if pix.width * pix.height < MIN_PDF_IMAGE_PIXELS or pix.width * pix.height > MAX_PIXELS:
                continue
            gray = pix.colorspace is not None and pix.colorspace.n == 1
            if pix.alpha or pix.colorspace is None or pix.colorspace.n != 3:
                pix = fitz.Pixmap(fitz.csRGB, pix, 0)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            cleaned, stats = clean_image(img, **options)
            if not (stats["light_px"] or stats["color_px"]):
                continue
            if gray:
                cleaned = cleaned.convert("L")
            buf = io.BytesIO()
            if doc.extract_image(xref).get("ext") in ("jpg", "jpeg", "jpx"):
                cleaned.save(buf, format="JPEG", quality=90)
            else:
                cleaned.save(buf, format="PNG", optimize=True)
            page.replace_image(xref, stream=buf.getvalue())
            changed += 1
    return changed
