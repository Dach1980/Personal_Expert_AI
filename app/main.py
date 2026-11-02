"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.middleware import UploadBodyLimitMiddleware
from app.api.routes import router as api_router
from app.processing.api import router as processing_router
from app.storage.config import max_upload_bytes

app = FastAPI(
    title="Personal Expert AI",
    description="Local-first AI platform for project documentation analysis.",
    version="0.1.0",
)


app.add_middleware(UploadBodyLimitMiddleware, max_bytes=max_upload_bytes())
app.include_router(api_router)
app.include_router(processing_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a basic process health response."""
    return {"status": "ok", "service": "personal-expert-ai"}
