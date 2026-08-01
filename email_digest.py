#!/usr/bin/env python3
"""
Sends the weekly digest to every confirmed EmailSubscription — the best
deals from the last DIGEST_WINDOW_DAYS in whatever categories they picked
(empty categories = every category), ranked by discount, dead links
excluded. Skips a subscriber entirely rather than sending an empty digest
if nothing matched.

Run on a schedule (see .github/workflows/email_digest.yml), not as part of
worker.py's daily ingest — a weekly cadence needs its own trigger, and
keeping it a separate script means a digest-sending failure can't block
ingest or vice versa.

Usage: python3 email_digest.py [--dry-run]
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, or_, select

from db import PRICE_TRACKED_CATEGORIES, SessionLocal, init_db
from email_sender import is_configured, send_email
from models import Deal, EmailSubscription

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.hackthedeal.com"
API_BASE_URL = os.getenv("API_BASE_URL", "https://deal-scanner-api.onrender.com")
DIGEST_WINDOW_DAYS = 7
DEALS_PER_DIGEST = 8

# Kept in sync with CATEGORY_LABELS in scripts/generate_category_pages.py —
# small and stable enough that duplicating it here beats importing across
# a script/ boundary that isn't a package. Only used for display text.
CATEGORY_LABELS = {
    "amazon_finds": "Amazon Finds", "black_friday": "Black Friday", "christmas": "Christmas",
    "back_to_school": "Back to School", "computers": "Computers", "gaming": "Gaming",
    "apple": "Apple", "cameras": "Cameras", "software": "Software", "streaming": "Streaming",
    "trading_cards": "Trading Cards", "fashion": "Fashion", "beauty": "Beauty", "shoes": "Shoes",
    "travel": "Travel", "drones": "Drones", "3d_printing": "3D Printing", "filament": "3D Filament",
}


def _format_price(value, currency: str = "USD") -> str | None:
    if value is None:
        return None
    return f"${value:,.2f}" if currency == "USD" else f"{value:,.2f} {currency}"


def fetch_digest_deals(session, categories: list[str], limit: int = DEALS_PER_DIGEST) -> list[Deal]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DIGEST_WINDOW_DAYS)
    q = select(Deal).where(
        Deal.confidence >= 0.5,
        Deal.is_dead.is_(False),
        Deal.posted_at >= cutoff,
        Deal.category.notin_(PRICE_TRACKED_CATEGORIES),
    )
    if categories:
        q = q.where(Deal.category.in_(categories))
    q = q.order_by(desc(Deal.discount_pct).nulls_last(), desc(Deal.posted_at)).limit(limit)
    return list(session.execute(q).scalars().all())


def render_digest_html(deals: list[Deal], unsubscribe_url: str) -> str:
    rows = []
    for deal in deals:
        target = deal.affiliate_url or deal.url
        price = _format_price(deal.deal_price, deal.currency)
        discount = f"{round(deal.discount_pct)}% off" if deal.discount_pct else None
        meta = " · ".join(x for x in [price, discount, CATEGORY_LABELS.get(deal.category, deal.category)] if x)
        rows.append(f"""
        <tr><td style="padding:14px 0;border-bottom:1px solid #2a2d3f">
          <a href="{target}" style="color:#7aa2f7;font-weight:700;font-size:15px;text-decoration:none">{deal.title}</a>
          <div style="color:#838dc0;font-size:13px;margin-top:4px">{meta}</div>
        </td></tr>""")

    return f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto;background:#1c1e2e;color:#d3dbfa;padding:24px">
      <h1 style="font-size:20px;margin:0 0 4px">This week's best deals</h1>
      <p style="color:#838dc0;font-size:13px;margin:0 0 20px">Hand-picked from the last week, ranked by discount.</p>
      <table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>
      <p style="margin-top:24px"><a href="{BASE_URL}/" style="color:#7aa2f7">See all deals →</a></p>
      <p style="font-size:11px;color:#5b6178;margin-top:32px">
        You're getting this because you subscribed to Hack the Deal's weekly digest.
        <a href="{unsubscribe_url}" style="color:#5b6178">Unsubscribe</a>
      </p>
    </div>"""


def send_weekly_digest(dry_run: bool = False) -> tuple[int, int]:
    init_db()
    sent = skipped = 0
    with SessionLocal() as session:
        subs = session.execute(
            select(EmailSubscription).where(EmailSubscription.confirmed.is_(True))
        ).scalars().all()

        for sub in subs:
            categories = [c for c in sub.categories.split(",") if c]
            deals = fetch_digest_deals(session, categories)
            if not deals:
                logger.info("Skipping %s — no matching deals this week", sub.email)
                skipped += 1
                continue

            unsubscribe_url = f"{API_BASE_URL}/email/unsubscribe?token={sub.token}"
            html = render_digest_html(deals, unsubscribe_url)

            if dry_run:
                logger.info("[dry-run] Would send %d deals to %s", len(deals), sub.email)
            else:
                if send_email(sub.email, "This week's best deals — Hack the Deal", html):
                    sub.last_sent_at = datetime.now(timezone.utc)
                    session.commit()
            sent += 1

    return sent, skipped


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if not dry_run and not is_configured():
        logger.error("RESEND_API_KEY is not set — refusing to run a real send. Use --dry-run to preview.")
        sys.exit(1)
    sent, skipped = send_weekly_digest(dry_run=dry_run)
    logger.info("Digest done. %d sent, %d skipped (no matching deals).", sent, skipped)
