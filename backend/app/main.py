"""The FastAPI application.

One request is one database transaction (see ``app.db.db_session``), and every
business rule failure is rendered in the single error shape the frontend expects.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import auth, clients, holdings, instructions, opening, operations, reference, reports
from app.api import users as users_api
from app.config import get_settings
from app.errors import AppError

logger = logging.getLogger("fms")

DESCRIPTION = """
Fund management for segregated, Shariah-compliant client mandates.

* Money is never a float: amounts and rates travel as strings.
* The ledger is double-entry and append-only; mistakes are corrected by reversal.
* Nothing leaves custody without a signed instruction the custodian has confirmed.
* Terminology is Shariah-compliant throughout: profit, never interest.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Shariah Fund Management System",
        version="1.0.0",
        description=DESCRIPTION,
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
    )

    for router in (
        auth.router,
        users_api.router,
        reference.router,
        clients.router,
        opening.router,
        holdings.router,
        instructions.router,
        operations.router,
        reports.router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:  # pragma: no cover
            logger.exception("unhandled application error", exc_info=exc)
        return JSONResponse(status_code=exc.status, content=exc.payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "the request body or query string is not valid",
                    "details": {"errors": _clean(exc.errors())},
                }
            },
        )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        response = await call_next(request)
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["cache-control"] = "no-store"
        return response

    @app.get("/api/v1/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    return app


def _clean(errors: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for error in errors:
        out.append(
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
        )
    return out


app = create_app()
