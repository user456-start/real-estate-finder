"""
Thin wrapper that initialises the llm-observer SDK once at startup and
provides a pre-wrapped Ollama client for use throughout the app.

Install the SDK before running:
    cd backend
    uv sync
    uv pip install -e /root/electronics/sdk

Pull the models once with Ollama:
    ollama pull llama3.2          # chat / generation
    ollama pull nomic-embed-text  # embeddings (replaces text-embedding-3-small)

How it fits in the architecture
────────────────────────────────
Every LLM call made through `get_ollama_client()` is automatically captured
as a span in the observability backend (http://localhost:8000). Cost is always
$0.00 since Ollama runs locally.

For pipeline nodes and tool calls, wrap the call site in `trace()` / `span()`
so the dashboard shows a full trace tree:

    from app.observability import get_ollama_client, trace, span

    with trace(name="email_pipeline", tags={"pipeline": "daily_email"}) as t:
        t.set_input({"preferences": prefs})

        with span(name="aggregator", type="tool") as s:
            s.set_input({"platforms": ["bayut", "property_finder"]})
            listings = run_aggregator(prefs)
            s.set_output({"count": len(listings)})

        with span(name="rag_retrieval", type="retrieval") as s:
            s.set_input({"area": "JLT", "query": "vibe"})
            chunks = area_guide_rag("JLT", "vibe and highlights")
            s.set_output({"chunks": len(chunks)})

        # LLM call — auto-captured as a child span under the trace
        client = get_ollama_client()
        response = client.chat(
            model=settings.OLLAMA_CHAT_MODEL,
            messages=[{"role": "user", "content": "..."}],
        )
        text = response.message.content

        t.set_output({"email_sent": True})

LangGraph / LangChain integration
───────────────────────────────────
For LangGraph nodes use ChatOllama directly (separate from the observed raw client):

    from langchain_ollama import ChatOllama
    llm = ChatOllama(model=settings.OLLAMA_CHAT_MODEL, base_url=settings.OLLAMA_BASE_URL)

LangChain calls are NOT captured by the llm-observer wrapper because they bypass
the raw ollama.Client. To observe them, add a custom LangChain callback — or
simply call the raw observed client for generation steps and reserve ChatOllama
for LangGraph tool routing.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_ollama_client = None


def init_observer() -> None:
    """
    Call once from FastAPI lifespan. Safe to call multiple times — idempotent.
    If llm-observer is not installed, logs a warning and falls back to a plain
    ollama.Client() so the app always starts.
    """
    global _ollama_client
    try:
        import ollama
        from llm_observer import Observer

        Observer.init(
            base_url=settings.LLM_OBSERVER_URL,
            api_key=settings.LLM_OBSERVER_API_KEY,
            enabled=True,
        )
        raw_client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        _ollama_client = Observer.wrap_ollama(raw_client)
        logger.info(
            "llm-observer initialised — Ollama @ %s, traces → %s",
            settings.OLLAMA_BASE_URL,
            settings.LLM_OBSERVER_URL,
        )
    except ImportError as exc:
        logger.warning(
            "Dependency not installed (%s). "
            "Run: cd backend && uv sync && uv pip install -e /root/electronics/sdk\n"
            "Falling back to un-instrumented Ollama client.",
            exc,
        )
        import ollama
        _ollama_client = ollama.Client(host=settings.OLLAMA_BASE_URL)
    except Exception as exc:
        logger.warning("llm-observer init failed (%s). Continuing without observability.", exc)
        import ollama
        _ollama_client = ollama.Client(host=settings.OLLAMA_BASE_URL)


def get_ollama_client():
    """
    Returns the observed (or plain) ollama.Client.
    Always use this instead of constructing ollama.Client() directly so that
    every chat() call is automatically traced.

    Usage:
        client = get_ollama_client()
        response = client.chat(
            model=settings.OLLAMA_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are a Dubai real-estate expert."},
                {"role": "user",   "content": user_message},
            ],
        )
        reply = response.message.content
    """
    if _ollama_client is None:
        init_observer()
    return _ollama_client


def embed(text: str) -> list[float]:
    """
    Generate an embedding vector using Ollama (nomic-embed-text).
    Returns a list[float] of length EMBEDDING_DIM (768 for nomic-embed-text).

    Note: EMBEDDING_DIM in models.py must match the model's output dimension.
    nomic-embed-text → 768 dims.  Change the constant if you switch models.
    """
    import ollama
    client = ollama.Client(host=settings.OLLAMA_BASE_URL)
    response = client.embeddings(model=settings.OLLAMA_EMBED_MODEL, prompt=text)
    return response["embedding"]


# Re-export context primitives so callers only need one import
try:
    from llm_observer import trace, span, observe, Prompt  # noqa: F401
except ImportError:
    # Stubs — no-ops when SDK is not installed
    from contextlib import contextmanager
    from functools import wraps

    @contextmanager
    def trace(name="", **_):  # type: ignore[misc]
        class _T:
            def set_input(self, *a, **k): pass
            def set_output(self, *a, **k): pass
        yield _T()

    @contextmanager
    def span(name="", **_):  # type: ignore[misc]
        class _S:
            def set_input(self, *a, **k): pass
            def set_output(self, *a, **k): pass
        yield _S()

    def observe(name=None, **_):  # type: ignore[misc]
        def decorator(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                return fn(*a, **kw)
            return wrapper
        return decorator

    class Prompt:  # type: ignore[no-redef]
        @staticmethod
        def get(name): raise LookupError("llm-observer SDK not installed")
        @staticmethod
        def create(*a, **k): raise ConnectionError("llm-observer SDK not installed")
