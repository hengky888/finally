"""Health check for Docker and deployment probes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Liveness check. Deliberately free of database or market dependencies."""
    return {"status": "ok"}
