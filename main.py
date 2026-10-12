"""
Contact Sheet — entry point. The app itself lives in the `app/` package:

  app/main.py                     -> create_app(): routers, error handlers, static frontend
  app/core/config.py              -> limits, paths
  app/core/errors.py              -> unexpected errors -> JSON {"detail": ...}
  app/core/pdf_utils.py           -> open/validate uploaded PDFs, PDF responses, page ranges
  app/core/image_utils.py         -> open/validate uploaded images
  app/services/background_removal.py -> u2netp via onnxruntime
  app/routers/
    health.py      GET  /api/health
    convert.py     POST /api/pdf-to-images, /api/images-to-pdf
    pdf_merge.py   POST /api/pdf/combine, /api/pdf/inspect, /api/pdf/build
    pdf_pages.py   POST /api/pdf/remove-pages
    pdf_stamp.py   POST /api/pdf/stamp
    pdf_crop.py    POST /api/pdf/crop-resize
    image.py       POST /api/image/compress, /api/image/remove-bg

Run with `uvicorn main:app --reload` or `python main.py`.
"""

from app.main import app  # noqa: F401  (re-exported for `uvicorn main:app`)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
