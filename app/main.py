"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="Personal Expert AI",
    description="Local-first AI platform for project documentation analysis.",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a basic process health response."""
    return {"status": "ok", "service": "personal-expert-ai"}
