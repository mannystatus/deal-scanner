import html
import itertools
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

import httpx
from dotenv import load_dotenv

load_dotenv()

from db import init_db, get_session, upsert_deal, deal_exists, get_deal_by_url, update_deal_price
from db import PRICE_TRACKED_CATEGORIES
from notifications import notify_new_deal
from parsers import parse_title
from reddit_source import iter_all_subreddits
from rss_source import iter_all_feeds

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_UA = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: mannydotco@gmail.com)")

# Skip stale entries (e.g. evergreen coupon listings with an old pubDate) so
# the DB doesn't accumulate deals that are already too old to ever be shown.
_MAX_DEAL_AGE_DAYS = int(os.getenv("MAX_DEAL_AGE_DAYS", "30"))
_OG_PROP_FIRST = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_CONTENT_FIRST = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)

# DealNews wraps outbound purchase links in its own click-tracking redirect
# (e.g. data-href="https://www.dealnews.com/lw/click.html?..."). Fetching
# that URL returns a tiny page with a JS `location.replace(...)` pointing at
# the real retailer link — which, for Amazon, already carries DealNews' own
# affiliate tag. We swap it for ours so the commission comes to us instead.
_DEALNEWS_CLICK_RE = re.compile(r'data-href="(https://www\.dealnews\.com/lw/click\.html[^"]*)"')
_JS_REDIRECT_RE = re.compile(r"location\.replace\('([^']+)'\)")

# Slickdeals wraps its outbound "Get Deal at ..." button in a slickdeals.net/click
# redirect that 302s straight to the retailer — for Amazon, already carrying
# Slickdeals' own affiliate tag (e.g. tag=slickdeals09b-20). We swap it for ours.
_SLICKDEALS_OUTCLICK_RE = re.compile(r'class="dealDetailsOutclickButton[^"]*"[^>]*href="([^"]+)"')

_AMAZON_TAG = os.getenv("AMAZON_AFFILIATE_TAG", "wisedealsxyz-20")


def _is_amazon_host(url: str) -> bool:
    return "amazon." in (urlparse(url).hostname or "")


def _extract_og_image(html: str) -> Optional[str]:
    snippet = html[:60_000]
    m = _OG_PROP_FIRST.search(snippet) or _OG_CONTENT_FIRST.search(snippet)
    return m.group(1) if m else None


def _retag_amazon_url(url: str, tag: str) -> str:
    parts = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(parts.query) if k != "tag"]
    params.append(("tag", tag))
    return urlunparse(parts._replace(query=urlencode(params)))


def _resolve_dealnews_amazon_link(page_html: str) -> Optional[str]:
    click_match = _DEALNEWS_CLICK_RE.search(page_html)
    if not click_match:
        return None
    try:
        resp = httpx.get(click_match.group(1), headers={"User-Agent": _UA}, timeout=10, follow_redirects=True)
        redirect_match = _JS_REDIRECT_RE.search(resp.text)
        if not redirect_match:
            return None
        dest = redirect_match.group(1)
        if not _is_amazon_host(dest):
            return None
        return _retag_amazon_url(dest, _AMAZON_TAG)
    except Exception:
        return None


def _resolve_slickdeals_amazon_link(page_html: str) -> Optional[str]:
    click_match = _SLICKDEALS_OUTCLICK_RE.search(page_html)
    if not click_match:
        return None
    click_url = html.unescape(click_match.group(1))
    try:
        resp = httpx.get(click_url, headers={"User-Agent": _UA}, timeout=10, follow_redirects=True)
        dest = str(resp.url)
        if not _is_amazon_host(dest):
            return None
        return _retag_amazon_url(dest, _AMAZON_TAG)
    except Exception:
        return None


def fetch_page_extras(url: str, source: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (thumbnail_url, affiliate_url) for a deal's source page."""
    # Some feeds link straight to the Amazon product page rather than routing
    # through a click-tracker, and often with no "tag" param — or someone
    # else's — at all. Retag it directly so we don't need the page fetch
    # below to succeed for this to work.
    affiliate_url = None
    if _is_amazon_host(url):
        affiliate_url = _retag_amazon_url(url, _AMAZON_TAG)

    try:
        resp = httpx.get(url, headers={"User-Agent": _UA}, timeout=10, follow_redirects=True)
    except Exception:
        return None, affiliate_url

    thumbnail_url = _extract_og_image(resp.text)
    if affiliate_url is None:
        if source.startswith("dealnews"):
            affiliate_url = _resolve_dealnews_amazon_link(resp.text)
        elif source.startswith("slickdeals"):
            affiliate_url = _resolve_slickdeals_amazon_link(resp.text)
    return thumbnail_url, affiliate_url


def main() -> int:
    db_url = os.getenv("DATABASE_URL", "sqlite:///deals.db")
    parsed_url = urlparse(db_url)
    logger.info("Connecting to: %s://%s%s", parsed_url.scheme, parsed_url.hostname or "(local)", parsed_url.path)
    if not (db_url.startswith("postgresql") or db_url.startswith("sqlite")):
        logger.error(
            "DATABASE_URL must be a PostgreSQL or SQLite URL, got %r. "
            "Set DATABASE_URL in Render → deal-scanner-worker → Environment, then redeploy.",
            db_url,
        )
        return -1
    init_db()
    total_new = 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_DEAL_AGE_DAYS)

    with get_session() as session:
        for post in itertools.chain(iter_all_feeds(), iter_all_subreddits()):
            if post["posted_at"] < cutoff:
                continue
            parsed = parse_title(post["title"], post["url"], post["source"])

            if parsed.category in PRICE_TRACKED_CATEGORIES:
                existing = get_deal_by_url(session, parsed.url)
                if existing is not None:
                    update_deal_price(session, existing, parsed, recorded_at=datetime.now(timezone.utc))
                    continue

            thumbnail_url = None
            if not deal_exists(session, parsed.url):
                thumbnail_url, affiliate_url = fetch_page_extras(parsed.url, post["source"])
                parsed.affiliate_url = affiliate_url
                logger.debug("Thumbnail for %s: %s", parsed.url, thumbnail_url)
                if affiliate_url:
                    logger.info("Retagged Amazon link for %s", parsed.url)
            if upsert_deal(
                session,
                parsed,
                subreddit=post["source"],
                reddit_id=post["reddit_id"],
                posted_at=post["posted_at"],
                thumbnail_url=thumbnail_url,
            ):
                total_new += 1
                notify_new_deal(session, parsed, thumbnail_url)

    logger.info("Done. %d total new deals ingested.", total_new)
    return total_new


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
