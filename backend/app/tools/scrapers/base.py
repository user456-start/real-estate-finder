"""
Base scraper — Playwright browser session with network interception,
retry logic, and incremental-stop support.

Why Playwright instead of httpx:
  Bayut and Property Finder sit behind CloudFront + JS CAPTCHA challenges
  that block plain HTTP clients (401/302 to captchaChallenge). A real
  Chromium browser passes these checks automatically.

Network interception strategy:
  Rather than parsing HTML, we let the page load normally and intercept
  the internal XHR/fetch calls the JS frontend makes to the listing API.
  We capture those JSON payloads directly — cleaner than DOM scraping.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from tenacity import RetryError, before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.tools.scrapers.normalizer import RawListing

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, asyncio.TimeoutError, Exception)) and \
           "Timeout" in type(exc).__name__


class BaseScraper(ABC):
    platform_name: str
    max_pages: int = 20
    page_size: int = 25
    request_delay: float = 2.0   # seconds between pages

    # Realistic browser fingerprint
    _launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-blink-features=AutomationControlled",
    ]
    _viewport = {"width": 1440, "height": 900}
    _locale = "en-US"
    _timezone = "Asia/Dubai"

    def __init__(self) -> None:
        self._browser = None
        self._context = None
        self._playwright = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=self._launch_args,
        )
        self._context = await self._browser.new_context(
            viewport=self._viewport,
            locale=self._locale,
            timezone_id=self._timezone,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        # Hide webdriver flag that sites check for
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return self

    async def __aexit__(self, *_):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scrape(
        self,
        preferences: dict[str, Any],
        since: datetime | None = None,
    ) -> list[RawListing]:
        """Fetch all pages. The `since` parameter is intentionally ignored —
        RapidAPI's `listed_date` is the original posting date, not a last-updated
        timestamp, so filtering by it drops active listings. The Postgres upsert
        (ON CONFLICT DO UPDATE) handles duplicates efficiently."""
        all_listings: list[RawListing] = []
        page = 1

        while page <= self.max_pages:
            try:
                page_results = await self._fetch_with_retry(preferences, page)
            except RetryError as exc:
                logger.error("[%s] page %d failed after all retries: %s", self.platform_name, page, exc)
                break

            if not page_results:
                break

            all_listings.extend(page_results)

            logger.info("[%s] page %d → %d listings", self.platform_name, page, len(page_results))
            page += 1
            await asyncio.sleep(self.request_delay)

        logger.info("[%s] total: %d listings", self.platform_name, len(all_listings))
        return all_listings

    async def _fetch_with_retry(self, preferences: dict[str, Any], page: int) -> list[RawListing]:
        @retry(
            retry=retry_if_exception(lambda e: "Timeout" in type(e).__name__),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=16),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        async def _inner():
            return await self.fetch_page(preferences, page)
        return await _inner()

    @staticmethod
    def _is_newer_than(raw: RawListing, since: datetime) -> bool:
        updated = raw.get("updated_at")
        if updated is None:
            return True
        if isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated)
            except ValueError:
                return True
        return updated.replace(tzinfo=None) > since.replace(tzinfo=None)

    async def _new_page(self):
        """Open a fresh page in the shared browser context."""
        assert self._context is not None
        return await self._context.new_page()

    @abstractmethod
    async def fetch_page(self, preferences: dict[str, Any], page: int) -> list[RawListing]:
        ...
