"""
FastAPI application entry point.

Prerequisites:
    # 1. Install deps and configure environment
    cd backend
    uv sync
    cp .env.example .env

    # 2. Start DB + Redis, run migrations, seed
    cd .. && docker compose up -d && cd backend
    alembic upgrade head
    python -m app.services.seeder

Run:
    cd backend
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.vector_store import get_qdrant


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ─────────────────────────────────────────────────────────
    get_qdrant().ensure_collections()  # creates Qdrant collections if missing
    start_scheduler()                  # ETL every 6h (00:00, 06:00, 12:00, 18:00 Dubai time)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    stop_scheduler()


app = FastAPI(
    title="Dubai Real-Estate Finder",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ──────────────────────────────────────────────────────────────────
# Uncomment as each phase is implemented:
# from app.routes import properties, chat, email_pipeline
# app.include_router(properties.router, prefix="/api")
# app.include_router(chat.router,       prefix="/api")
# app.include_router(email_pipeline.router, prefix="/api")

from app.routes import chat, properties

app.include_router(chat.router)
app.include_router(properties.router)


@app.get("/health")
def health():
    return {"status": "ok"}
