"""
Embeddings generation using Hugging Face (nomic-embed-text via sentence-transformers).

Usage:
    from app.observability import embed

    embedding = embed("This is a property description")
    print(len(embedding))  # 768 dimensions

The observability/tracing context managers (trace, span) are provided as stubs
for backward compatibility, but do not perform any actual tracing.
"""

import logging
from contextlib import contextmanager
from functools import wraps

from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

# Global model instance (lazy-loaded on first use)
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the sentence transformer model."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def embed(text: str) -> list[float]:
    """
    Generate an embedding vector using Hugging Face (nomic-embed-text).
    Returns a list[float] of length 768 (nomic-embed-text output dimension).

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the embedding vector.
    """
    model = _get_model()
    # normalize=True matches the nomic-embed-text training setup
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


# ── Backward compatibility: stub context managers ──────────────────────────

@contextmanager
def trace(name: str = "", **_):  # type: ignore[misc]
    """
    Stub trace context manager for backward compatibility.
    Does not perform any actual tracing — just yields a context object.
    """
    class _T:
        def set_input(self, *a, **k): pass
        def set_output(self, *a, **k): pass
    yield _T()


@contextmanager
def span(name: str = "", **_):  # type: ignore[misc]
    """
    Stub span context manager for backward compatibility.
    Does not perform any actual tracing — just yields a context object.
    """
    class _S:
        def set_input(self, *a, **k): pass
        def set_output(self, *a, **k): pass
    yield _S()


def init_observer(**_):  # type: ignore[misc]
    """
    Stub init_observer function for backward compatibility.
    Does not perform any actual initialization.
    """
    pass


def observe(name: str | None = None, **_):  # type: ignore[misc]
    """
    Stub decorator for backward compatibility.
    Does not perform any actual tracing — just passes through the function.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            return fn(*a, **kw)
        return wrapper
    return decorator


class Prompt:  # type: ignore[no-redef]
    """Stub Prompt class for backward compatibility."""
    @staticmethod
    def get(name):
        raise LookupError("Prompts module not available")

    @staticmethod
    def create(*a, **k):
        raise ConnectionError("Prompts module not available")
