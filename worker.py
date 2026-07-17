import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

from db import init_db, get_session, upsert_deal, deal_exists
from parsers import parse_title
from rss_source import iter_all_feeds

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_UA = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: mannydotco@gmail.com)")

# Skip stale entries (e.g. evergreen coupon listings with an old pubDate) so
# the DB doesn't accumulate deals that are already too old to ever be shown.
_MAX_DEAL_AGE_DAYS = int(os.getenv("MAX_DEAL_AGE_DAYS", "100"))
_OG_PROP_FIRST = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_CONTENT_FIRST = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)


def fetch_og_image(url: str) -> Optional[str]:
    try:
        resp = httpx.get(url, headers={"User-Agent": _UA}, timeout=10, follow_redirects=True)
        snippet = resp.text[:60_000]
        m = _OG_PROP_FIRST.search(snippet) or _OG_CONTENT_FIRST.search(snippet)
        return m.group(1) if m else None
    except Exception:
        return None


def main() -> int:
    from urllib.parse import urlparse
    db_url = os.getenv("DATABASE_URL", "sqlite:///deals.db")
    parsed_url = urlparse(db_url)
    logger.info("Connecting to: %s://%s%s", parsed_url.scheme, parsed_url.hostname or "(local)", parsed_url.path)
    if not db_url.startswith("postgresql"):
        logger.error(
            "DATABASE_URL is not set to a PostgreSQL URL. "
            "Set DATABASE_URL in Render → deal-scanner-worker → Environment, then redeploy."
        )
        return -1
    init_db()
    total_new = 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_DEAL_AGE_DAYS)

    with get_session() as session:
        for post in iter_all_feeds():
            if post["posted_at"] < cutoff:
                continue
            parsed = parse_title(post["title"], post["url"], post["source"])
            thumbnail_url = None
            if not deal_exists(session, parsed.url):
                thumbnail_url = fetch_og_image(parsed.url)
                logger.debug("Thumbnail for %s: %s", parsed.url, thumbnail_url)
            if upsert_deal(
                session,
                parsed,
                subreddit=post["source"],
                reddit_id=post["reddit_id"],
                posted_at=post["posted_at"],
                thumbnail_url=thumbnail_url,
            ):
                total_new += 1

    logger.info("Done. %d total new deals ingested.", total_new)
    return total_new


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
