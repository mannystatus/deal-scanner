"""
RSS-based deal ingestion — no Reddit account or API key required.

Pulls from public RSS/Atom feeds on popular deal sites.
Add or remove feeds via the FEED_URLS env var (comma-separated) or
edit DEFAULT_FEEDS below.
"""
import calendar
import hashlib
import html
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)

# One quick retry for 429/5xx — but only if the server's own Retry-After
# is short. A CI runner's shared IP can trip a vendor's rate limiter over
# a single brief spike, and that clears in a few seconds. But some vendors
# (Shopify, confirmed here) return a long Retry-After (60s+) while
# sustained-blocking a whole shared IP range — waiting that out per feed
# would eat the entire job's time budget for a retry that's going to fail
# anyway, so those are treated as a fast, non-retried failure instead.
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 1
_RETRY_DELAY = 3          # seconds, used when there's no Retry-After header
_MAX_HONORED_RETRY_AFTER = 5  # ignore server-requested waits longer than this

# Pause between feeds so requests to different vendor sites don't all land
# in the same second — that burst pattern is exactly what trips shared
# rate limiters in the first place.
_INTER_FEED_DELAY = 1


def _get_with_retry(url: str, headers: dict, timeout: int = 30) -> httpx.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        if int(retry_after) > _MAX_HONORED_RETRY_AFTER:
                            resp.raise_for_status()  # not worth waiting out — fail fast
                        delay = int(retry_after)
                    except ValueError:
                        pass
                logger.warning(
                    "  %s returned %d, retrying in %ds (attempt %d/%d)",
                    url, resp.status_code, delay, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last_exc = e
            break
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
                continue
            break
    raise last_exc

# (source_name, rss_url)
DEFAULT_FEEDS: list[tuple[str, str]] = [
    ("slickdeals",   "https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1"),
    ("slickdeals",   "https://slickdeals.net/newsearch.php?mode=popdeals&searcharea=deals&searchin=first&rss=1"),
    ("dealnews",     "https://www.dealnews.com/c142/Electronics/?rss=1"),
    ("dealnews",     "https://www.dealnews.com/c39/Computers/?rss=1"),
    ("9to5toys",     "https://9to5toys.com/feed/"),
    ("9to5mac",      "https://9to5mac.com/guides/deals/feed/"),
    ("dealnews-fashion", "https://www.dealnews.com/c202/Clothing-Accessories/?rss=1"),
    ("dealnews-shoes",   "https://www.dealnews.com/c280/Clothing-Accessories/Shoes/?rss=1"),
    ("dealnews-beauty",  "https://www.dealnews.com/c756/Health-Beauty/?rss=1"),
    ("dealnews-travel",  "https://www.dealnews.com/c206/Travel-Entertainment/?rss=1"),
    ("dealnews-software", "https://www.dealnews.com/c124/Computers/Software/?rss=1"),
    # Brand-direct searches, so deals surface from the brands themselves
    # instead of general deal-blog aggregators.
    ("slickdeals-nike",       "https://slickdeals.net/newsearch.php?q=nike&rss=1"),
    ("slickdeals-adidas",     "https://slickdeals.net/newsearch.php?q=adidas&rss=1"),
    ("slickdeals-levis",      "https://slickdeals.net/newsearch.php?q=levi&rss=1"),
    ("slickdeals-rei",        "https://slickdeals.net/newsearch.php?q=rei&rss=1"),
    ("slickdeals-northface",  "https://slickdeals.net/newsearch.php?q=the+north+face&rss=1"),
    # Trading card searches — Slickdeals posts already name which retailer
    # (Amazon, Target, Walmart, Best Buy, etc.) is running each deal.
    ("slickdeals-pokemon",       "https://slickdeals.net/newsearch.php?q=pokemon+tcg&rss=1"),
    ("slickdeals-mtg",           "https://slickdeals.net/newsearch.php?q=magic+the+gathering&rss=1"),
    ("slickdeals-yugioh",        "https://slickdeals.net/newsearch.php?q=yugioh&rss=1"),
    ("slickdeals-panini",        "https://slickdeals.net/newsearch.php?q=panini+trading+cards&rss=1"),
    ("slickdeals-topps",         "https://slickdeals.net/newsearch.php?q=topps+baseball&rss=1"),
    ("slickdeals-tradingcards",  "https://slickdeals.net/newsearch.php?q=trading+cards&rss=1"),
    # Direct-from-vendor Shopify "sale" collection feeds — real deals
    # straight from the retailer, not a third-party aggregator.
    ("pyrodrone",     "https://pyrodrone.com/collections/sale.atom"),
    ("racedayquads",  "https://www.racedayquads.com/collections/sale.atom"),
    ("dronenerds",    "https://www.dronenerds.com/collections/sale.atom"),
    ("elegoo",        "https://www.elegoo.com/collections/sale.atom"),
    ("anycubic",      "https://store.anycubic.com/collections/sale.atom"),
    ("sovol",         "https://www.sovol3d.com/collections/sale.atom"),
    ("polymaker",     "https://shop.polymaker.com/collections/sale.atom"),
    ("overture",      "https://overture3d.com/collections/sale.atom"),
]

# WooCommerce stores queried via their public Store API for on-sale products
# (no RSS/Atom feed available). (source_name, store_base_url)
WOOCOMMERCE_STORES: list[tuple[str, str]] = [
    ("myfpvstore", "https://www.myfpvstore.com"),
]

# Shopify's Atom feed embeds price as HTML in the summary rather than the
# title (e.g. "<strong>Price: </strong>79.99"). Extracted and folded into
# the title so the existing $-price regex in parsers.py picks it up.
_SHOPIFY_PRICE_RE = re.compile(r'Price:\s*</strong>\s*([\d,]+\.\d+)', re.S)


def _shopify_price(summary: str) -> str | None:
    m = _SHOPIFY_PRICE_RE.search(summary or "")
    return m.group(1) if m else None


def _load_feeds() -> list[tuple[str, str]]:
    """Allow overriding feeds via FEED_URLS env var (format: 'source|url,source|url')."""
    raw = os.getenv("FEED_URLS", "").strip()
    if not raw:
        return DEFAULT_FEEDS
    feeds = []
    for entry in raw.split(","):
        entry = entry.strip()
        if "|" in entry:
            source, url = entry.split("|", 1)
            feeds.append((source.strip(), url.strip()))
    return feeds or DEFAULT_FEEDS


def _make_id(url: str) -> str:
    """Stable short ID derived from the URL (mirrors the Reddit ID field)."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _parse_time(t) -> datetime:
    """Convert feedparser's time_struct to a UTC datetime."""
    if t is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def iter_feed(source: str, url: str) -> Iterator[dict]:
    """Fetch one RSS/Atom feed and yield normalized post dicts."""
    ua = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: tech@hackthedeal.com)")
    try:
        resp = _get_with_retry(url, headers={"User-Agent": ua})
        raw = resp.text
    except httpx.HTTPError as e:
        logger.error("Failed to fetch feed %s (%s): %s", source, url, e)
        return

    feed = feedparser.parse(raw)
    if feed.bozo and not feed.entries:
        logger.warning("Feed parse issue for %s: %s", url, feed.bozo_exception)
        return

    logger.info("  %s: %d entries", source, len(feed.entries))
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link  = (entry.get("link")  or "").strip()
        if not title or not link:
            continue

        if "$" not in title:
            price = _shopify_price(entry.get("summary"))
            if price:
                title = f"{title} - ${price}"

        posted_at = _parse_time(
            entry.get("published_parsed") or entry.get("updated_parsed")
        )
        yield {
            "reddit_id": _make_id(link),  # same field name as the old Reddit source
            "title":     title,
            "url":       link,
            "posted_at": posted_at,
            "source":    source,
        }


def iter_woocommerce_store(source: str, base_url: str, max_pages: int = 3) -> Iterator[dict]:
    """Fetch on-sale products from a WooCommerce store's public Store API.

    No published-date field is exposed by this API, so posted_at is set to
    the ingestion time — first-seen ordering, same as everything else here
    once a deal is already in the DB (upsert_deal never revisits old rows).
    """
    ua = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: tech@hackthedeal.com)")
    total = 0
    for page in range(1, max_pages + 1):
        url = f"{base_url}/wp-json/wc/store/v1/products?on_sale=true&per_page=100&page={page}"
        try:
            resp = httpx.get(url, headers={"User-Agent": ua}, timeout=30)
            resp.raise_for_status()
            items = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to fetch WooCommerce store %s page %d: %s", source, page, e)
            return
        if not items:
            break
        total += len(items)
        for item in items:
            name = html.unescape(item.get("name") or "")
            link = item.get("permalink") or ""
            prices = item.get("prices") or {}
            if not name or not link:
                continue
            try:
                minor = int(prices.get("currency_minor_unit", 2))
                scale = 10 ** minor
                sale = int(prices["sale_price"]) / scale
                regular = int(prices["regular_price"]) / scale
            except (KeyError, TypeError, ValueError):
                continue

            title = f"{name} - ${sale:.2f}"
            if regular > sale:
                title = f"{name} - ${sale:.2f} (was ${regular:.2f})"

            yield {
                "reddit_id": _make_id(link),
                "title":     title,
                "url":       link,
                "posted_at": datetime.now(timezone.utc),
                "source":    source,
            }
        if len(items) < 100:
            break
    logger.info("  %s: %d on-sale entries", source, total)


# Bambu Lab's store (bambulab.com's own custom Next.js storefront, not
# Shopify/WooCommerce) has no feed or public API — but the product grid
# IS server-rendered into the page, embedded as a JSON string inside
# Next.js's React Server Components payload (a series of
# `self.__next_f.push([1, "..."])` script calls that, concatenated and
# JSON-unescaped, reconstruct into one big JSON-ish text blob containing
# a "productList" array). No browser/JS execution needed — just a plain
# GET and some text surgery. (source_name, collection_url)
BAMBULAB_COLLECTIONS: list[tuple[str, str]] = [
    ("bambulab", "https://us.store.bambulab.com/collections/bambu-lab-3d-printer-filament"),
]

_NEXT_F_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,(".*?")\]\)(?=\s*</script>)', re.S)


def iter_bambulab_collection(source: str, collection_url: str) -> Iterator[dict]:
    """Scrape a Bambu Lab store collection page for its product list."""
    import json as _json
    from urllib.parse import urlparse

    ua = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: tech@hackthedeal.com)")
    headers = {"User-Agent": ua, "Accept": "text/html"}
    try:
        resp = _get_with_retry(collection_url, headers=headers)
        raw = resp.text
    except httpx.HTTPError as e:
        logger.error("Failed to fetch Bambu Lab collection %s (%s): %s", source, collection_url, e)
        return

    chunks = _NEXT_F_PUSH_RE.findall(raw)
    full_text = ""
    for chunk in chunks:
        try:
            full_text += _json.loads(chunk)
        except _json.JSONDecodeError:
            continue

    idx = full_text.find('"productList":[')
    if idx == -1:
        logger.error("Bambu Lab collection %s: productList not found (page structure may have changed)", source)
        return
    try:
        products, _ = _json.JSONDecoder().raw_decode(full_text, idx + len('"productList":'))
    except _json.JSONDecodeError as e:
        logger.error("Bambu Lab collection %s: failed to parse productList: %s", source, e)
        return

    base = f"{urlparse(collection_url).scheme}://{urlparse(collection_url).netloc}"
    total = 0
    for p in products:
        name = (p.get("name") or "").strip()
        seo_code = p.get("seo_code") or p.get("seoCode") or ""
        sale = p.get("lowerPrice")
        original = p.get("price")
        if not name or not seo_code or sale is None:
            continue

        title = f"{name} - ${sale:.2f}"
        if original is not None and original > sale:
            title = f"{name} - ${sale:.2f} (was ${original:.2f})"

        link = f"{base}/products/{seo_code}"
        yield {
            "reddit_id": _make_id(link),
            "title":     title,
            "url":       link,
            "posted_at": datetime.now(timezone.utc),
            "source":    source,
        }
        total += 1
    logger.info("  %s: %d products", source, total)


def iter_all_feeds() -> Iterator[dict]:
    """Iterate over all configured feeds and yield post dicts."""
    for i, (source, url) in enumerate(_load_feeds()):
        if i > 0:
            time.sleep(_INTER_FEED_DELAY)
        logger.info("Fetching %s — %s", source, url)
        yield from iter_feed(source, url)
    for source, base_url in WOOCOMMERCE_STORES:
        time.sleep(_INTER_FEED_DELAY)
        logger.info("Fetching %s (WooCommerce store) — %s", source, base_url)
        yield from iter_woocommerce_store(source, base_url)
    for source, collection_url in BAMBULAB_COLLECTIONS:
        time.sleep(_INTER_FEED_DELAY)
        logger.info("Fetching %s (Bambu Lab collection) — %s", source, collection_url)
        yield from iter_bambulab_collection(source, collection_url)
