"""
Qdrant vector store — manages the three embedding collections.

Collections
───────────
  area_guide_chunks    Area guide text chunks, keyed by area_name
  poi_descriptions     POI description chunks, keyed by poi_id (Postgres UUID)
  listing_descriptions Listing description, keyed by listing_id (Postgres UUID)

All collections use nomic-embed-text embeddings (768-dim, local Ollama).

Usage:
    from app.services.vector_store import get_qdrant, search_area_guides

    # On startup / seeder — ensure collections exist
    get_qdrant().ensure_collections()

    # Index a chunk
    get_qdrant().upsert_area_guide_chunk(
        area_name="JLT",
        chunk_id="jlt-0",
        text="JLT is a high-rise district ...",
        embedding=[0.1, 0.2, ...],
    )

    # Search
    results = get_qdrant().search_area_guide(
        area_name="JLT",
        query_vector=[0.1, 0.2, ...],
        top_k=3,
    )
"""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768          # nomic-embed-text output dimension

COLLECTION_AREA_GUIDES  = "area_guide_chunks"
COLLECTION_POIS         = "poi_descriptions"
COLLECTION_LISTINGS     = "listing_descriptions"


class VectorStore:
    def __init__(self, url: str) -> None:
        self._client = QdrantClient(url=url)

    # ── Collection management ─────────────────────────────────────────────

    def ensure_collections(self) -> None:
        """Create collections if they don't already exist. Safe to call on every startup."""
        existing = {c.name for c in self._client.get_collections().collections}
        for name in (COLLECTION_AREA_GUIDES, COLLECTION_POIS, COLLECTION_LISTINGS):
            if name not in existing:
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
                )
                logger.info("Qdrant: created collection '%s'", name)
            else:
                logger.debug("Qdrant: collection '%s' already exists", name)

    # ── Area guide chunks ─────────────────────────────────────────────────

    def upsert_area_guide_chunk(
        self,
        area_name: str,
        chunk_id: str,
        text: str,
        embedding: list[float],
    ) -> None:
        self._client.upsert(
            collection_name=COLLECTION_AREA_GUIDES,
            points=[
                PointStruct(
                    id=_str_to_uint(chunk_id),
                    vector=embedding,
                    payload={"area_name": area_name, "text": text},
                )
            ],
        )

    def search_area_guide(
        self,
        area_name: str,
        query_vector: list[float],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Semantic search scoped to a single area."""
        results = self._client.search(
            collection_name=COLLECTION_AREA_GUIDES,
            query_vector=query_vector,
            query_filter=Filter(
                must=[FieldCondition(key="area_name", match=MatchValue(value=area_name))]
            ),
            limit=top_k,
            with_payload=True,
        )
        return [{"text": r.payload["text"], "score": r.score} for r in results]

    # ── POI descriptions ──────────────────────────────────────────────────

    def upsert_poi(
        self,
        poi_id: str,
        text: str,
        embedding: list[float],
        poi_type: str,
        name: str,
    ) -> None:
        self._client.upsert(
            collection_name=COLLECTION_POIS,
            points=[
                PointStruct(
                    id=_str_to_uint(poi_id),
                    vector=embedding,
                    payload={"poi_id": poi_id, "type": poi_type, "name": name, "text": text},
                )
            ],
        )

    def search_pois(
        self,
        poi_ids: list[str],
        query_vector: list[float],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Semantic search scoped to a specific set of POI IDs (output of nearby_places)."""
        results = self._client.search(
            collection_name=COLLECTION_POIS,
            query_vector=query_vector,
            query_filter=Filter(
                must=[FieldCondition(key="poi_id", match=MatchValue(value=pid))]
                for pid in poi_ids
            ) if poi_ids else None,
            limit=top_k,
            with_payload=True,
        )
        return [{"text": r.payload["text"], "name": r.payload["name"], "score": r.score}
                for r in results]

    # ── Listing descriptions ──────────────────────────────────────────────

    def upsert_listing(
        self,
        listing_id: str,
        text: str,
        embedding: list[float],
        area_name: str,
        price_aed: float | None,
    ) -> None:
        self._client.upsert(
            collection_name=COLLECTION_LISTINGS,
            points=[
                PointStruct(
                    id=_str_to_uint(listing_id),
                    vector=embedding,
                    payload={
                        "listing_id": listing_id,
                        "text": text,
                        "area_name": area_name,
                        "price_aed": price_aed,
                    },
                )
            ],
        )

    def search_listings(
        self,
        query_vector: list[float],
        area_name: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search over listing descriptions, optionally filtered by area."""
        area_filter = (
            Filter(must=[FieldCondition(key="area_name", match=MatchValue(value=area_name))])
            if area_name
            else None
        )
        results = self._client.search(
            collection_name=COLLECTION_LISTINGS,
            query_vector=query_vector,
            query_filter=area_filter,
            limit=top_k,
            with_payload=True,
        )
        return [{"listing_id": r.payload["listing_id"], "text": r.payload["text"], "score": r.score}
                for r in results]


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: VectorStore | None = None


def get_qdrant() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(url=settings.QDRANT_URL)
    return _store


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str_to_uint(s: str) -> int:
    """
    Qdrant point IDs must be unsigned integers or UUIDs.
    Convert a string (UUID or arbitrary chunk ID) to a stable uint64
    by hashing it.
    """
    import hashlib
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % (2**63)
