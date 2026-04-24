"""
FastAPI application entry point.

Prerequisites:
    # 1. Ollama running locally with models pulled
    ollama pull llama3.2
    ollama pull nomic-embed-text

    # 2. Install SDK and deps
    cd backend
    uv sync
    uv pip install -e /root/electronics/sdk

    # 3. Start DB + Redis, run migrations, seed
    cd .. && docker compose up -d && cd backend
    alembic upgrade head
    python -m app.services.seeder

Run:
    cd backend
    cp .env.example .env
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.observability import init_observer
from app.services.vector_store import get_qdrant


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ─────────────────────────────────────────────────────────
    init_observer()                    # wraps Ollama client with llm-observer SDK
    get_qdrant().ensure_collections()  # creates Qdrant collections if missing
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    # Flush any pending observability events before process exits
    try:
        from llm_observer import Observer
        Observer.flush(timeout=5.0)
    except ImportError:
        pass


app = FastAPI(
    title="Dubai Real-Estate Finder",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],   # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ──────────────────────────────────────────────────────────────────
# Uncomment as each phase is implemented:
# from app.routes import properties, chat, email_pipeline
# app.include_router(properties.router, prefix="/api")
# app.include_router(chat.router,       prefix="/api")
# app.include_router(email_pipeline.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
