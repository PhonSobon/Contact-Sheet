"""Turns unexpected exceptions into JSON so the frontend can show a real
message instead of a generic fallback (a plain-text 500 can't be parsed)."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("contact_sheet")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Server error while processing this file: {exc}"},
        )
