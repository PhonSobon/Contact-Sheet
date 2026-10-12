"""Builds the FastAPI app: registers routers, error handlers, and the static frontend."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import SITE_URL, STATIC_DIR
from app.core.errors import register_error_handlers
from app.routers import (
    convert,
    health,
    image,
    image_watermark,
    pdf_crop,
    pdf_merge,
    pdf_pages,
    pdf_stamp,
    pdf_watermark,
)

logging.basicConfig(level=logging.INFO)


def _site_url(request: Request) -> str:
    """Absolute base URL for link-preview meta tags. Prefers the SITE_URL
    setting; otherwise uses the request's host, honouring the X-Forwarded-*
    headers that hosting proxies (Vercel, Render, nginx...) set for https."""
    if SITE_URL:
        return SITE_URL
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host.split(',')[0].strip()}"


def create_app() -> FastAPI:
    app = FastAPI(title="Contact Sheet", version="1.0.0")

    # CORS is only needed if you ever split the frontend onto another origin.
    # Same-origin (this app serving both API + page) doesn't need it, but it's
    # harmless to leave open here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    for module in (health, convert, pdf_merge, pdf_pages, pdf_stamp, pdf_watermark, pdf_crop, image, image_watermark):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def serve_index(request: Request):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("%SITE_URL%", _site_url(request)))

    # Browsers request /favicon.ico on their own; serve the SVG icon there too.
    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon():
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    # Any other static assets (css/js/images) placed in static/ are served as-is,
    # e.g. static/foo.png -> /foo.png. Mounted last so it never shadows /api/*.
    app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
