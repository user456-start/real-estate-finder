"""
Index area guides and listing descriptions into Qdrant for RAG search.

Run once after seeding, and re-run whenever new listings are added:
    cd backend
    uv run python scripts/index_vectors.py

What it does:
    1. Loads nomic-embed-text-v1.5 locally via sentence-transformers
    2. Embeds all area guides from the DB → upserts into Qdrant
    3. Embeds all listing descriptions from the DB → upserts into Qdrant
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentence_transformers import SentenceTransformer
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import AreaGuide, Listing
from app.services.vector_store import get_qdrant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


def load_model() -> SentenceTransformer:
    logger.info("Loading embedding model %s ...", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)
    logger.info("Model loaded.")
    return model


def index_area_guides(model: SentenceTransformer) -> None:
    db = SessionLocal()
    try:
        guides = db.execute(select(AreaGuide)).scalars().all()
        logger.info("Indexing %d area guides ...", len(guides))

        qdrant = get_qdrant()
        qdrant.ensure_collections()

        for guide in guides:
            embedding = model.encode(f"search_document: {guide.content}").tolist()
            qdrant.upsert_area_guide_chunk(
                area_name=guide.area_name,
                chunk_id=f"area-{guide.area_name}",
                text=guide.content,
                embedding=embedding,
            )
            logger.info("  ✓ %s", guide.area_name)

        logger.info("Area guides indexed: %d", len(guides))
    finally:
        db.close()


def index_listings(model: SentenceTransformer, batch_size: int = 100) -> None:
    db = SessionLocal()
    try:
        listings = db.execute(
            select(Listing).where(Listing.available == True)
        ).scalars().all()
        logger.info("Indexing %d listings ...", len(listings))

        qdrant = get_qdrant()
        total = 0

        for i in range(0, len(listings), batch_size):
            batch = listings[i : i + batch_size]

            texts = []
            for l in batch:
                text = (
                    f"{l.title or ''}. "
                    f"{l.beds or '?'} bed, {l.baths or '?'} bath, "
                    f"{int(l.size_sqft) if l.size_sqft else '?'} sqft. "
                    f"Area: {l.area_name or 'Dubai'}. "
                    f"Price: AED {int(l.price_aed) if l.price_aed else '?'}/year. "
                    f"{'Rental' if l.is_rental else 'For sale'}."
                )
                texts.append(f"search_document: {text}")

            embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)

            for l, embedding in zip(batch, embeddings):
                qdrant.upsert_listing(
                    listing_id=str(l.id),
                    text=texts[batch.index(l)].replace("search_document: ", ""),
                    embedding=embedding.tolist(),
                    area_name=l.area_name or "",
                    price_aed=float(l.price_aed) if l.price_aed else None,
                )
                total += 1

            logger.info("  indexed %d / %d", min(i + batch_size, len(listings)), len(listings))

        logger.info("Listings indexed: %d", total)
    finally:
        db.close()


if __name__ == "__main__":
    model = load_model()
    index_area_guides(model)
    index_listings(model)
    logger.info("All done! Qdrant is ready for RAG search.")
