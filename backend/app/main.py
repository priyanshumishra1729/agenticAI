import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from app.core.config import settings  # noqa: I001  (sets telemetry env vars first)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.a2a.server import router as a2a_router
from app.api.routes import router as api_router
from app.seed import seed_demo_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
for noisy in ("mcp", "httpx", "LiteLLM", "google_adk", "google.adk", "opentelemetry"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
# ADK's OTel spans inside async generators log harmless "Failed to detach context" errors.
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

os.makedirs(settings.upload_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_demo_data()
    yield
    from app.observability import tracer

    tracer.flush()


app = FastAPI(title="SignalChain – Autonomous Supply Chain Crisis Management", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(a2a_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


# Serve the built React app (single-container deployment).
_dist = Path(settings.frontend_dist)
if _dist.joinpath("index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = _dist / full_path
        if full_path and candidate.is_file() and _dist in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
