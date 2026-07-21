#!/usr/bin/env python3
"""
Backfill thumbnail_url for all existing deals and set affiliate_url for Amazon
deals with tag=wisedealsxyz-20.

For Amazon URLs (amazon.com, a.co, amzn.to) the script:
  - Follows the redirect to the canonical amazon.com product URL
  - Adds ?tag=wisedealsxyz-20 to the resolved URL and saves it as affiliate_url
  - Never overwrites an affiliate_url that is already set

For all deals it also fetches og:image and saves it as thumbnail_url.

Usage:
    python migrate_thumbnails.py               # backfill all NULL thumbnails
    python migrate_thumbnails.py --dry-run     # preview without writing to DB
    python migrate_thumbnails.py --delay 0.4   # seconds between requests (default 0.4)
    python migrate_thumbnails.py --limit 20    # process at most N deals (testing)
"""
import argparse
import logging
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///deals.db")
AMAZON_TAG = "wisedealsxyz-20"
_UA = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: tech@hackthedeal.com)")

_OG_PROP_FIRST = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_CONTENT_FIRST = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)

_AMAZON_HOSTS = {"amazon.com", "www.amazon.com", "smile.amazon.com"}
_AMAZON_SHORTLINK_HOSTS = {"a.co", "amzn.to", "amzn.com"}


def is_amazon(url: str) -> bool:
    host = urlparse(url).netloc.lower().lstrip("www.")
    return host in _AMAZON_HOSTS or host in _AMAZON_SHORTLINK_HOSTS


def add_amazon_tag(url: str) -> str:
    """Return the URL with tag=wisedealsxyz-20 added (or replaced) in the query string."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["tag"] = [AMAZON_TAG]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def fetch_deal_data(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch the deal page and return (thumbnail_url, resolved_url).

    thumbnail_url  — og:image value, or None if not found / request failed.
    resolved_url   — final URL after all redirects (useful for a.co → amazon.com).
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _UA},
            timeout=12,
            follow_redirects=True,
        )
        final_url = str(resp.url)
        snippet = resp.text[:60_000]
        m = _OG_PROP_FIRST.search(snippet) or _OG_CONTENT_FIRST.search(snippet)
        return (m.group(1) if m else None), final_url
    except Exception as exc:
        logger.debug("  fetch failed (%s): %s", type(exc).__name__, exc)
        return None, None


def add_column_if_missing(engine) -> None:
    with engine.connect() as conn:
        if DATABASE_URL.startswith("sqlite"):
            cols = [
                row[1]
                for row in conn.execute(text("PRAGMA table_info(deals)")).fetchall()
            ]
            if "thumbnail_url" not in cols:
                conn.execute(text("ALTER TABLE deals ADD COLUMN thumbnail_url TEXT"))
                conn.commit()
                logger.info("Added thumbnail_url column (SQLite).")
            else:
                logger.info("thumbnail_url column already present.")
        else:
            conn.execute(
                text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS thumbnail_url TEXT")
            )
            conn.commit()
            logger.info("Ensured thumbnail_url column exists (PostgreSQL).")


def run(dry_run: bool, delay: float, limit: Optional[int]) -> None:
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
    add_column_if_missing(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        rows = session.execute(
            text(
                "SELECT id, url, affiliate_url FROM deals "
                "WHERE thumbnail_url IS NULL ORDER BY id"
            )
        ).fetchall()
    except Exception as exc:
        logger.error("Query failed: %s", exc)
        session.close()
        sys.exit(1)

    if limit:
        rows = rows[:limit]

    total = len(rows)
    logger.info(
        "Deals to process: %d%s", total, "  [dry-run]" if dry_run else ""
    )

    BATCH = 50
    thumbs_set = affiliates_set = no_image = 0

    for i, (deal_id, url, existing_affiliate) in enumerate(rows, 1):
        logger.info("[%d/%d] id=%-6d  %s", i, total, deal_id, url[:80])

        thumbnail, resolved_url = fetch_deal_data(url)

        new_affiliate: Optional[str] = None
        if resolved_url and is_amazon(resolved_url) and not existing_affiliate:
            new_affiliate = add_amazon_tag(resolved_url)
            logger.info("  affiliate -> %s", new_affiliate[:80])

        if thumbnail:
            logger.info("  thumb    -> %s", thumbnail[:80])
            thumbs_set += 1
        else:
            logger.info("  thumb    -> (none)")
            no_image += 1

        if new_affiliate:
            affiliates_set += 1

        if not dry_run:
            session.execute(
                text(
                    "UPDATE deals SET thumbnail_url = :thumb"
                    + (", affiliate_url = :aff" if new_affiliate else "")
                    + " WHERE id = :id"
                ),
                {
                    "thumb": thumbnail,
                    "id": deal_id,
                    **({"aff": new_affiliate} if new_affiliate else {}),
                },
            )

        if not dry_run and i % BATCH == 0:
            session.commit()
            logger.info("  — committed %d/%d", i, total)

        if i < total:
            time.sleep(delay)

    if not dry_run:
        session.commit()

    session.close()
    logger.info(
        "Done.  thumbnails=%d  no-image=%d  amazon-affiliates-tagged=%d  total=%d%s",
        thumbs_set,
        no_image,
        affiliates_set,
        total,
        "  [dry-run, nothing written]" if dry_run else "",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch data but do not write anything to the database.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        metavar="SECS",
        help="Seconds to wait between HTTP requests (default: 0.4).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N deals (useful for a quick test run).",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, delay=args.delay, limit=args.limit)
