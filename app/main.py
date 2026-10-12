"""Builds the FastAPI app: registers routers, error handlers, and the static frontend."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import STATIC_DIR
from app.core.errors import register_error_handlers
from app.routers import convert, health, image, pdf_crop, pdf_merge, pdf_pages, pdf_stamp

logging.basicConfig(level=logging.INFO)


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

    for module in (health, convert, pdf_merge, pdf_pages, pdf_stamp, pdf_crop, image):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

    # Any other static assets (css/js/images) placed in static/ are served as-is,
    # e.g. static/foo.png -> /foo.png. Mounted last so it never shadows /api/*.
    app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
