from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(100))
    reddit_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    affiliate_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deal_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    original_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    discount_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="other")
    merchant: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_deals_category_posted", "category", "posted_at"),
        Index("ix_deals_posted_at", "posted_at"),
    )


class PriceHistory(Base):
    """A price snapshot for a deal over time. Only populated for categories
    that track a persistent catalog (e.g. filament), where the same product
    URL is re-checked on every ingest run rather than posted once."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    original_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    discount_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    """A browser's Web Push subscription, plus which deal categories it
    wants notifications for (empty string = every category)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    categories: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SocialPost(Base):
    """Records a deal having been posted to a social platform, so the poster
    script never posts the same deal to the same platform twice."""

    __tablename__ = "social_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"))
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("deal_id", "platform", name="uq_social_posts_deal_platform"),
    )
