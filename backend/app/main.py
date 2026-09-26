"""FastAPI application entry point for ODYSSEY TRANSFORM CORE."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import PIPELINE_VERSION, get_settings
from .db import init_db
from .routers import audit, documents, outputs, system, transformations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("odyssey")

settings = get_settings()

DESCRIPTION = """
**ODYSSEY TRANSFORM CORE** - source-grounded Generative AI platform that turns one
verified source into many consistent, secure, audience-specific communication artefacts.

* Smart India Hackathon 2026 - Problem Statement SIH26154
* Team ODYSSEY NEXUS | Theme: Blockchain & Cybersecurity
* Transform Information. Preserve Trust. Accelerate Action.
"""

TAGS_METADATA = [
    {"name": "system", "description": "Health, capabilities, configuration and security scanning."},
    {"name": "documents", "description": "Multimodal ingestion: upload, paste, URL. Sanitised, chunked, embedded, understood."},
    {"name": "transformations", "description": "Source-grounded multi-format generation, comparison and provenance."},
    {"name": "outputs", "description": "Preview, edit, regenerate, human review, export and integrity verification."},
    {"name": "audit", "description": "Tamper-evident hash-chained audit trail."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    settings.ensure_directories()
    logger.info(
        "%s v%s ready | env=%s | db=%s | llm=%s",
        settings.app_name,
        PIPELINE_VERSION,
        settings.environment,
        settings.database_url,
        "configured" if settings.llm_configured else "extractive-only",
    )
    yield


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version=__version__,
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal pipeline error",
            "error_type": type(exc).__name__,
            "path": request.url.path,
        },
    )


for router in (system.router, documents.router, transformations.router, outputs.router, audit.router):
    app.include_router(router, prefix=settings.api_prefix)


# The built dashboard, when present. Resolved before the root route is declared
# so `/` can hand a browser the app instead of a JSON banner.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_SPA_BUNDLED = _dist.is_dir()

SERVICE_BANNER = {
    "app": settings.app_name,
    "version": __version__,
    "team": "ODYSSEY NEXUS",
    "problem_statement": "SIH26154 - Gen AI Platform for Automated Content Transformation",
    "docs": "/docs",
    "api": settings.api_prefix,
    "tagline": "Transform Information. Preserve Trust. Accelerate Action.",
}


@app.get(f"{settings.api_prefix}/info", include_in_schema=False)
def service_info() -> dict:
    """Identity banner: who this is, which problem statement, where the docs are."""
    return {**SERVICE_BANNER, "dashboard_bundled": _SPA_BUNDLED}


@app.get("/", include_in_schema=False, response_model=None)
def root() -> Response:
    """The dashboard when it is bundled, otherwise the service banner.

    A browser pointed at the port must land on the app. When no build is
    present (API-only deployment) the banner is the most useful thing to return.
    """
    if _SPA_BUNDLED:
        return FileResponse(_dist / "index.html", media_type="text/html")
    return JSONResponse(SERVICE_BANNER)


if _SPA_BUNDLED:
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # Deep links outside the API must fall through to the SPA shell, but an
        # unknown /api path is a client error: answering 200 with HTML would hide
        # typos behind a misleading success.
        if full_path == settings.api_prefix.strip("/") or full_path.startswith(
            f"{settings.api_prefix.strip('/')}/"
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No API route matches /{full_path}",
            )
        candidate = _dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
