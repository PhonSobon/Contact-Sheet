"""App-wide limits and paths. Change upload/page limits here."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "static"

MAX_PDF_BYTES = 40 * 1024 * 1024       # 40 MB
MAX_IMAGE_BYTES = 20 * 1024 * 1024     # 20 MB per image
MAX_PAGES = 400                         # safety cap for JSON+thumbnail payload
MAX_COMBINE_PDFS = 10                   # simple combine flow, in selected order
MAX_INSPECT_PDFS = 10                   # page editor / combine grid
MAX_BG_REMOVAL_IMAGES = 15              # this one's CPU-heavy, keep batches small

# PDF -> Images has its own input-size limit (20 MB) separate from
# MAX_PDF_BYTES above, which is shared by the merge/build/stamp/crop tools.
P2I_MAX_PDF_BYTES = 20 * 1024 * 1024   # 20 MB
P2I_MAX_PAGES = 400                    # total across all uploaded PDFs
P2I_MAX_FILES = 10

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
    os.getenv("U2NETP_MODEL_PATH", str(PROJECT_ROOT / "model" / "u2netp.onnx"))
)
U2NETP_DOWNLOAD_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
