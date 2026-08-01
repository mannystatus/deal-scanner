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
    # Community vote count at ingest time — Slickdeals' "Thumb Score" or a
    # Reddit post's score (ups - downs). Null for sources with no voting
    # (DealNews, 9to5toys, WooCommerce/Bambulab catalogs), not re-fetched
    # after ingest, same as every other field here (see upsert_deal).
    vote_score: Mapped[Optional[int]] = mapped_column(nullable=True)
    # Outbound-link liveness, rechecked periodically after ingest rather
    # than only determined once (see link_health.py). Dead deals aren't
    # hidden or deleted — they keep showing with an "Expired" badge instead
    # of the live CTA. link_checked_at is null until the first recheck pass
    # reaches this deal.
    is_dead: Mapped[bool] = mapped_column(default=False)
    link_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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


class EmailSubscription(Base):
    """A weekly-digest email subscriber, plus which deal categories they
    want (empty string = every category). Double opt-in: confirmed=False
    until the subscriber clicks the link in the confirmation email (see
    api.py's /email/confirm), so send_weekly_digest() never mails an
    address nobody verified. token is reused for both the confirm link and
    the unsubscribe link — a single unguessable value is enough for both,
    no separate secret needed."""

    __tablename__ = "email_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    categories: Mapped[str] = mapped_column(Text, default="")
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    confirmed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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
