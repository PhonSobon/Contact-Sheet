"""
Background removal with u2netp, run directly through onnxruntime instead of
the `rembg` package. `rembg` is fine for a normal server, but it
unconditionally imports pymatting/scipy/scikit-image at module load time
(for an alpha-matting feature we never use), which alone adds 300+MB of
dependencies — enough to blow past serverless platforms' function-size
limits (e.g. Vercel's 250-500MB caps). Calling onnxruntime directly with the
same model and the same pre/post-processing rembg uses produces
byte-identical output without that weight.
"""

import numpy as np
import onnxruntime as ort
from PIL import Image

from app.core.config import U2NETP_DOWNLOAD_URL, U2NETP_MODEL_PATH

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


def remove_background(img: Image.Image) -> Image.Image:
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
