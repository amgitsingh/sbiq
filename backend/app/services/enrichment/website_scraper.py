from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.services.enrichment.source_toggle import toggleable

logger = logging.getLogger(__name__)

TIMEOUT_MS = 10_000
MAX_CHARS = 5_000
ABOUT_PATH = "/about"
_STRIP_TAGS = ("script", "style", "nav", "footer", "header", "noscript", "iframe", "svg", "form")


@toggleable("ENABLE_WEBSITE_SCRAPER", empty_value=None)
def scrape_company_website(url: str) -> str | None:
    """Fetch a company's homepage + /about page and return cleaned text.

    Never raises — returns None on any failure (bad URL, timeout, 404s on
    both pages, etc.) so one bad company never blocks an enrichment batch.
    """
    if not url or not url.strip():
        return None

    normalized_url = _normalize_url(url.strip())
    about_url = urljoin(normalized_url, ABOUT_PATH)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                homepage_text = _fetch_and_clean(page, normalized_url)
                about_text = _fetch_and_clean(page, about_url)
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"Failed to launch browser while scraping {normalized_url}: {e}")
        return None

    parts = [t for t in (homepage_text, about_text) if t]
    if not parts:
        logger.warning(f"No content scraped from {normalized_url} (homepage or {ABOUT_PATH})")
        return None

    combined = " ".join(parts)
    return combined[:MAX_CHARS]


def _normalize_url(url: str) -> str:
    if not urlparse(url).scheme:
        return f"https://{url}"
    return url


def _fetch_and_clean(page, target_url: str) -> str | None:
    try:
        response = page.goto(target_url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout loading {target_url}")
        return None
    except PlaywrightError as e:
        logger.warning(f"Navigation error loading {target_url}: {e}")
        return None

    if response is None:
        logger.warning(f"No response received for {target_url}")
        return None

    if response.status >= 400:
        logger.info(f"{target_url} returned HTTP {response.status}")
        return None

    html = page.content()
    cleaned = _clean_html(html)
    return _cap(cleaned, MAX_CHARS // 2)


def _clean_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _cap(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text[:limit]
