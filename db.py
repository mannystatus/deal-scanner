import hashlib
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from models import Base, Deal, PriceHistory
from parsers import ParsedDeal

# Categories that track a persistent catalog (same product URL every run)
# rather than one-off deal posts — these get their price updated and
# snapshotted over time instead of being ingested once and left frozen.
PRICE_TRACKED_CATEGORIES = {"filament"}

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///deals.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    parsed = urlparse(DATABASE_URL)
    logger.info("Connecting to: %s://%s%s", parsed.scheme, parsed.hostname or "(local)", parsed.path)

    # Render sets RENDER=true on every service it runs. If we're on Render but
    # DATABASE_URL isn't Postgres, the env var was never picked up — fail loudly
    # at startup instead of silently serving an empty local SQLite DB.
    if os.getenv("RENDER") and not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError(
            "DATABASE_URL is not set to a PostgreSQL URL on Render. "
            "Set DATABASE_URL in the Render dashboard -> deal-scanner-api -> "
            "Environment, then redeploy."
        )

    Base.metadata.create_all(engine)


# Tracking-only query params that vary by RSS feed/placement without
# identifying a different underlying deal — e.g. DealNews cross-posts the
# same article into both its Shoes and Clothing & Accessories feeds with
# only `iref` (rss-c280 vs rss-c202) differing, which used to defeat the
# URL-based dedup check below and double-ingest the same deal under two
# categories (see the "Adidas Samba OG" / "Adidas Ultraboost 22" duplicates
# that prompted this).
_DEDUP_STRIP_PARAMS = {"iref"}
_DEDUP_STRIP_PREFIXES = ("utm_",)


def _normalize_for_dedup(url: str) -> str:
    parsed = urlparse(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query)
        if k not in _DEDUP_STRIP_PARAMS and not k.startswith(_DEDUP_STRIP_PREFIXES)
    ]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def make_hash(url: str) -> str:
    return hashlib.sha256(_normalize_for_dedup(url).encode()).hexdigest()[:32]


@contextmanager
def get_session():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def deal_exists(session: Session, url: str) -> bool:
    return session.execute(
        select(Deal.id).where(Deal.dedup_hash == make_hash(url))
    ).scalar_one_or_none() is not None


def get_deal_by_url(session: Session, url: str) -> Deal | None:
    return session.execute(
        select(Deal).where(Deal.dedup_hash == make_hash(url))
    ).scalar_one_or_none()


def _num_changed(old, new, ndigits: int = 2) -> bool:
    """Compare a DB-loaded Decimal against a freshly-parsed float. A direct
    != comparison spuriously trips on float/Decimal binary-representation
    noise (e.g. Decimal('14.99') != 14.99), so round both sides first."""
    if old is None or new is None:
        return old is not new
    return round(float(old), ndigits) != round(float(new), ndigits)


def update_deal_price(session: Session, deal: Deal, parsed: ParsedDeal, recorded_at: datetime) -> bool:
    """Update a price-tracked deal's price fields if they've changed, logging
    a price-history point. Returns True if the price changed."""
    changed = (
        _num_changed(deal.deal_price, parsed.deal_price)
        or _num_changed(deal.original_price, parsed.original_price)
        or _num_changed(deal.discount_pct, parsed.discount_pct, ndigits=1)
    )
    if changed:
        deal.deal_price = parsed.deal_price
        deal.original_price = parsed.original_price
        deal.discount_pct = parsed.discount_pct
        session.add(
            PriceHistory(
                deal_id=deal.id,
                price=parsed.deal_price,
                original_price=parsed.original_price,
                discount_pct=parsed.discount_pct,
                recorded_at=recorded_at,
            )
        )
    return changed


def upsert_deal(
    session: Session,
    parsed: ParsedDeal,
    subreddit: str,
    reddit_id: str,
    posted_at: datetime,
    thumbnail_url: str | None = None,
) -> bool:
    dedup_hash = make_hash(parsed.url)
    exists = session.execute(
        select(Deal.id).where(Deal.dedup_hash == dedup_hash)
    ).scalar_one_or_none()
    if exists is not None:
        return False

    deal = Deal(
        dedup_hash=dedup_hash,
        source=subreddit,
        reddit_id=reddit_id,
        title=parsed.title,
        url=parsed.url,
        affiliate_url=parsed.affiliate_url,
        deal_price=parsed.deal_price,
        original_price=parsed.original_price,
        currency=parsed.currency,
        discount_pct=parsed.discount_pct,
        category=parsed.category,
        merchant=parsed.merchant,
        posted_at=posted_at,
        ingested_at=datetime.now(timezone.utc),
        confidence=parsed.confidence,
        thumbnail_url=thumbnail_url,
    )
    session.add(deal)

    if parsed.category in PRICE_TRACKED_CATEGORIES:
        session.flush()  # assign deal.id for the price-history FK
        session.add(
            PriceHistory(
                deal_id=deal.id,
                price=parsed.deal_price,
                original_price=parsed.original_price,
                discount_pct=parsed.discount_pct,
                recorded_at=posted_at,
            )
        )
    return True
