"""
Backfill image_url for existing listings using Playwright (sequential, reliable).

Usage:
    cd backend
    uv run python scripts/backfill_images.py            # all listings
    uv run python scripts/backfill_images.py --limit 50 # test with 50
    uv run python scripts/backfill_images.py --dry-run  # print URLs only

Sequential strategy (proven reliable):
    - Single warm-up page to establish WAF cookie
    - Sequential page navigation (one at a time)
    - ~22 seconds per listing = ~3.5 hours for 950 listings
    - No timeout/rate-limit issues
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update
from app.db.database import SessionLocal
from app.db.models import Listing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE   = 50
PAGE_TIMEOUT = 30_000   # ms for navigation
META_TIMEOUT = 20_000   # ms waiting for og:image to appear


async def fetch_one(page, listing_id: str, url: str) -> tuple[str, str | None]:
    """Fetch og:image from one URL using a pre-created page."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            await page.wait_for_selector('meta[property="og:image"]', timeout=META_TIMEOUT)
        except Exception:
            pass
        img = await page.evaluate(
            "document.querySelector('meta[property=\"og:image\"]')?.getAttribute('content')"
        )
        if img:
            logger.info("  ✓  %s", url[:70])
        else:
            logger.warning("  –  no og:image: %s", url[:70])
        return listing_id, img
    except Exception as e:
        logger.warning("  error (%s): %s", type(e).__name__, url[:60])
        return listing_id, None


async def main(limit: int | None, dry_run: bool) -> None:
    db = SessionLocal()
    try:
        q = (
            select(Listing.id, Listing.url)
            .where(Listing.image_url.is_(None))
            .where(Listing.url != "")
            .order_by(Listing.fetched_at.desc())
        )
        if limit:
            q = q.limit(limit)
        rows = db.execute(q).all()
    finally:
        db.close()

    total = len(rows)
    logger.info("Found %d listings without image_url", total)

    if total == 0:
        logger.info("Nothing to do.")
        return

    if dry_run:
        for r in rows[:20]:
            print(r.url)
        if total > 20:
            print(f"  ... and {total - 20} more")
        return

    from playwright.async_api import async_playwright

    updated = 0
    failed  = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="Asia/Dubai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Warm-up
        logger.info("Warming up browser...")
        warmup = await context.new_page()
        try:
            await warmup.goto("https://www.propertyfinder.ae/", wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(2)
            logger.info("Warm-up done.")
        except Exception as e:
            logger.warning("Warm-up failed: %s", e)
        finally:
            await warmup.close()

        # Sequential processing
        page = await context.new_page()
        for batch_start in range(0, total, BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]
            logger.info("Batch %d-%d / %d", batch_start + 1, min(batch_start + BATCH_SIZE, total), total)

            batch_results = []
            for r in batch:
                listing_id, image_url = await fetch_one(page, str(r.id), r.url)
                batch_results.append((listing_id, image_url))

            # Commit batch
            db = SessionLocal()
            try:
                for listing_id, image_url in batch_results:
                    if image_url:
                        db.execute(
                            update(Listing)
                            .where(Listing.id == listing_id)
                            .values(image_url=image_url)
                        )
                        updated += 1
                    else:
                        failed += 1
                db.commit()
                logger.info("  committed: updated=%d failed=%d (batch total)",
                           len([r for r in batch_results if r[1]]),
                           len([r for r in batch_results if not r[1]]))
            finally:
                db.close()

        await page.close()
        await context.close()
        await browser.close()

    logger.info("Backfill complete. updated=%d no_image=%d total=%d", updated, failed, total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=None, help="Max listings to process")
    parser.add_argument("--dry-run", action="store_true",    help="Print URLs only")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, dry_run=args.dry_run))
