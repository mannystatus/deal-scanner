import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

print(
    f"[boot] DATABASE_URL set={bool(os.getenv('DATABASE_URL'))} "
    f"starts_with_postgresql={os.getenv('DATABASE_URL', '').startswith('postgresql')} "
    f"RENDER={os.getenv('RENDER')!r}",
    file=sys.stderr,
    flush=True,
)

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, func, or_, select

from db import SessionLocal, engine, init_db
from models import Deal
from schemas import CategoryCount, DealListOut, DealOut, HealthOut

# Deals older than this never show, even if they're still sitting in the DB
# (e.g. stale evergreen listings, or old rows from a past ingestion source).
MAX_DEAL_AGE_DAYS = int(os.getenv("MAX_DEAL_AGE_DAYS", "30"))

# Sources retired from rss_source.py, but whose rows are still sitting in the
# DB from earlier ingestion runs. Blocked here so they stop showing without
# needing a DB migration.
BLOCKED_SOURCES = {"bensbargains"}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Deal Scanner API", version="0.1.0", lifespan=lifespan)

_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthOut)
def health():
    with SessionLocal() as session:
        count = session.execute(select(func.count(Deal.id))).scalar_one()
        latest = session.execute(
            select(Deal.ingested_at).order_by(desc(Deal.ingested_at)).limit(1)
        ).scalar_one_or_none()
    return HealthOut(status="ok", deal_count=count, latest_ingest=latest)


@app.get("/categories", response_model=list[CategoryCount])
def categories():
    with SessionLocal() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_DEAL_AGE_DAYS)
        rows = session.execute(
            select(Deal.category, func.count(Deal.id).label("count"))
            .where(Deal.posted_at >= cutoff, Deal.source.notin_(BLOCKED_SOURCES))
            .group_by(Deal.category)
            .order_by(desc("count"))
        ).all()
    return [CategoryCount(category=r.category, count=r.count) for r in rows]


@app.get("/deals", response_model=DealListOut)
def list_deals(
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_discount: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
    min_confidence: float = Query(0.5),
    limit: int = Query(30, le=100),
    offset: int = Query(0),
):
    with SessionLocal() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_DEAL_AGE_DAYS)
        q = select(Deal).where(
            Deal.confidence >= min_confidence,
            Deal.posted_at >= cutoff,
            Deal.source.notin_(BLOCKED_SOURCES),
        )
        if category:
            q = q.where(Deal.category == category)
        if source:
            q = q.where(Deal.source == source)
        if min_discount is not None:
            q = q.where(Deal.discount_pct >= min_discount)
        if max_price is not None:
            q = q.where(Deal.deal_price <= max_price)
        if search:
            term = f"%{search}%"
            q = q.where(or_(Deal.title.ilike(term), Deal.merchant.ilike(term)))

        total = session.execute(
            select(func.count()).select_from(q.subquery())
        ).scalar_one()
        items = session.execute(
            q.order_by(desc(Deal.posted_at)).limit(limit).offset(offset)
        ).scalars().all()

    return DealListOut(
        items=[DealOut.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/deals/{deal_id}", response_model=DealOut)
def get_deal(deal_id: int):
    with SessionLocal() as session:
        deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return DealOut.model_validate(deal)
