"""
Rechecks whether already-ingested deals' outbound links still resolve, and
flags the ones that don't as expired (see models.Deal.is_dead).

Deals aren't deleted or hidden when a link dies — they keep showing on
category/home pages and their permalink with an "Expired" badge instead of
the live CTA (see render_deal_card/build_deal_page in
scripts/generate_category_pages.py and DealCard in frontend/index.html).
That preserves crawl equity on the permalink and doesn't make a deal
silently vanish — the same reasoning already applied to keeping deal
permalinks live-but-noindexed after MAX_DEAL_AGE_DAYS.

Rechecking is a rotating slice (oldest-checked-first, batch_size per run,
called once per ingest — see worker.py) rather than every deal every run:
rechecking a few thousand outbound links to arbitrary retailer sites daily
would be a much bigger, slower job than ingest itself and more likely to
trip a retailer's rate limiting. At batch_size=200 and one ingest/day, a
deal is rechecked roughly once a week.
"""
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from db import PRICE_TRACKED_CATEGORIES
from models import Deal

logger = logging.getLogger(__name__)

_UA = os.getenv("RSS_USER_AGENT", "deal-scanner/0.1 (contact: tech@hackthedeal.com)")
_CHECK_DELAY = float(os.getenv("LINK_CHECK_DELAY", "0.3"))
_CHECK_TIMEOUT = float(os.getenv("LINK_CHECK_TIMEOUT", "10"))

# Statuses that mean "this specific page is gone" — confident enough to
# flag as dead. Everything else (403 bot-blocking, 429 rate limiting, 5xx,
# timeouts, TLS hiccups) is treated as inconclusive and left as-is rather
# than risk a false "Expired" from a site that's just blocking scrapers.
_DEAD_STATUSES = {404, 410}


def check_url(url: str) -> bool | None:
    """Returns True (alive), False (confirmed dead), or None (inconclusive)."""
    try:
        with httpx.stream(
            "GET", url, headers={"User-Agent": _UA}, timeout=_CHECK_TIMEOUT, follow_redirects=True
        ) as resp:
            if resp.status_code in _DEAD_STATUSES:
                return False
            if resp.status_code < 400:
                return True
            return None
    except httpx.ConnectError:
        # DNS failure or connection refused — the domain itself is gone,
        # not just blocking us.
        return False
    except httpx.HTTPError as e:
        logger.debug("Inconclusive link check for %s: %s", url, e)
        return None


def _active_deals_query(batch_size: int, cutoff: datetime):
    return (
        select(Deal)
        .where(
            Deal.confidence >= 0.5,
            or_(Deal.posted_at >= cutoff, Deal.category.in_(PRICE_TRACKED_CATEGORIES)),
        )
        .order_by(Deal.link_checked_at.is_(None).desc(), Deal.link_checked_at.asc())
        .limit(batch_size)
    )


def recheck_stale_links(session: Session, batch_size: int = 200, max_age_days: int = 30) -> tuple[int, int]:
    """Rechecks the batch_size active deals least-recently checked (never-
    checked ones first). Returns (checked_count, newly_dead_count)."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    deals = session.execute(_active_deals_query(batch_size, cutoff)).scalars().all()

    checked = 0
    newly_dead = 0
    for i, deal in enumerate(deals):
        target = deal.affiliate_url or deal.url
        result = check_url(target)
        deal.link_checked_at = datetime.now(timezone.utc)
        if result is not None:
            if result is False and not deal.is_dead:
                newly_dead += 1
                logger.info("Link dead: id=%d %s", deal.id, target[:80])
            deal.is_dead = not result
        checked += 1
        if i < len(deals) - 1:
            time.sleep(_CHECK_DELAY)

    session.commit()
    return checked, newly_dead
