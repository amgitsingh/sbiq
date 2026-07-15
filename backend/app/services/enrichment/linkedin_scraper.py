from __future__ import annotations

import logging
import re

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.services.enrichment.source_toggle import toggleable

logger = logging.getLogger(__name__)

TIMEOUT_MS = 10_000

# Any of these appearing in the final URL or page title signals LinkedIn served
# an auth-wall / checkpoint page instead of the real profile.
_BLOCK_MARKERS = ("/login", "/checkpoint", "/authwall", "/uas/login")


@toggleable("ENABLE_LINKEDIN_SCRAPER", empty_value=None)
def scrape_linkedin_profile(url: str) -> dict[str, str] | None:
    """Best-effort scrape of a public LinkedIn profile page.

    Returns a dict with any of "name", "title", "company", "about" that could
    be extracted, or None if the profile is unreachable, blocked (login wall,
    checkpoint, CAPTCHA), or yields no usable content. Never raises — a
    LinkedIn failure must never block the rest of enrichment. Only attempted
    once per call; callers must not retry the same participant within a run.
    """
    if not url or not url.strip():
        return None

    target_url = url.strip()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                profile = _fetch_profile(page, target_url)
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"Failed to launch browser while scraping LinkedIn {target_url}: {e}")
        return None

    return profile


def _fetch_profile(page, target_url: str) -> dict[str, str] | None:
    try:
        response = page.goto(target_url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
    except PlaywrightTimeoutError:
        logger.info(f"Timeout loading LinkedIn profile {target_url}")
        return None
    except PlaywrightError as e:
        logger.info(f"Navigation error loading LinkedIn profile {target_url}: {e}")
        return None

    if response is None:
        logger.info(f"No response received for LinkedIn profile {target_url}")
        return None

    if response.status >= 400:
        logger.info(f"LinkedIn profile {target_url} returned HTTP {response.status}")
        return None

    if _looks_blocked(page):
        logger.info(f"LinkedIn blocked scrape of {target_url} (login wall / checkpoint)")
        return None

    profile = _extract_profile(page)
    if not profile:
        logger.info(f"No extractable profile content for {target_url}")
        return None

    return profile


def _looks_blocked(page) -> bool:
    current_url = page.url or ""
    if any(marker in current_url for marker in _BLOCK_MARKERS):
        return True

    try:
        title = (page.title() or "").lower()
    except PlaywrightError:
        title = ""
    if "join linkedin" in title or "sign up" in title or "security verification" in title:
        return True

    return False


def _extract_profile(page) -> dict[str, str] | None:
    profile: dict[str, str] = {}

    name = _text_content(page, "h1")
    if name:
        profile["name"] = name

    title = _text_content(page, "div.text-body-medium")
    if title:
        profile["title"] = title
        company = _company_from_title(title)
        if company:
            profile["company"] = company

    about = _about_section(page)
    if about:
        profile["about"] = about

    return profile or None


def _text_content(page, selector: str) -> str | None:
    try:
        locator = page.locator(selector).first
        if locator.count() == 0:
            return None
        text = (locator.text_content() or "").strip()
    except PlaywrightError:
        return None
    return _clean_whitespace(text) or None


def _company_from_title(title: str) -> str | None:
    # LinkedIn's headline subtitle is commonly "<role> at <company>".
    match = re.search(r"\bat\s+(.+)$", title, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip() or None


def _about_section(page) -> str | None:
    try:
        section = page.locator("section:has(#about)").first
        if section.count() == 0:
            return None
        text = (section.text_content() or "").strip()
    except PlaywrightError:
        return None

    text = _clean_whitespace(text)
    # Strip the leading "About" section label itself, if present.
    text = re.sub(r"^About\s+", "", text, flags=re.IGNORECASE)
    return text or None


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
