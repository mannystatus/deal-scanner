import hashlib
import os
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from models import Base, Deal
from parsers import ParsedDeal

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///deals.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)


def make_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


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

    session.add(
        Deal(
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
    )
    return True
