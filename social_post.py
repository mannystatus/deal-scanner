"""Manually-triggered script that posts recent deals to X, Instagram, and/or
Threads.

Usage:
    python social_post.py                          # dry run, all configured platforms
    python social_post.py --live                    # actually post
    python social_post.py --platforms x,threads --live --limit 2 --min-discount 30

Deals are tracked per-platform in the social_posts table so nothing gets
posted twice, even across separate runs.
"""

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import desc, select

from db import get_session, init_db
from models import Deal, SocialPost
from social_platforms import POSTERS, PlatformNotConfigured, PostFailed, is_configured

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

ALL_PLATFORMS = ["x", "instagram", "threads"]

# X's t.co wrapper counts any URL as exactly 23 characters regardless of its
# real length, no matter the tier.
_X_URL_WEIGHT = 23
_PLATFORM_LIMITS = {"x": 280, "threads": 500, "instagram": 2200}


def _hashtag(category: str) -> str:
    return "#" + category.replace("_", "")


def compose_caption(deal: Deal, platform: str) -> str:
    link = deal.affiliate_url or deal.url
    url_weight = _X_URL_WEIGHT if platform == "x" else len(link)

    price_bit = ""
    if deal.deal_price is not None:
        price_bit = f"${deal.deal_price:g}"
        if deal.original_price is not None and deal.original_price > deal.deal_price:
            price_bit += f" (was ${deal.original_price:g})"

    discount_bit = f"{deal.discount_pct:.0f}% off — " if deal.discount_pct else ""
    merchant_bit = f" at {deal.merchant}" if deal.merchant else ""
    # FTC guidance requires the disclosure on the post itself, not just on a
    # linked page, hence "#ad" here rather than relying on the site's banner.
    tags = f"{_hashtag(deal.category)} #deals #ad"

    def build(title: str) -> str:
        parts = [f"{discount_bit}{title}{merchant_bit}"]
        if price_bit:
            parts.append(price_bit)
        parts.append(tags)
        return "\n".join(parts)

    limit = _PLATFORM_LIMITS[platform]
    budget = limit - url_weight - 1  # -1 for the newline before the link
    title = deal.title
    body = build(title)
    if len(body) > budget:
        overflow = len(body) - budget
        keep = max(len(title) - overflow - 1, 10)
        title = title[:keep].rstrip() + "…"
        body = build(title)

    return f"{body}\n{link}"


def get_candidates(
    session,
    platform: str,
    limit: int,
    min_discount: float,
    category: Optional[str],
) -> list[Deal]:
    already_posted = select(SocialPost.deal_id).where(SocialPost.platform == platform)
    q = select(Deal).where(Deal.confidence >= 0.5, Deal.id.notin_(already_posted))
    if min_discount:
        q = q.where(Deal.discount_pct >= min_discount)
    if category:
        q = q.where(Deal.category == category)
    if platform == "instagram":
        q = q.where(Deal.thumbnail_url.is_not(None))
    q = q.order_by(desc(Deal.posted_at)).limit(limit)
    return list(session.execute(q).scalars().all())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platforms", default=",".join(ALL_PLATFORMS), help=f"Comma-separated from: {', '.join(ALL_PLATFORMS)}")
    parser.add_argument("--limit", type=int, default=3, help="Max deals to post per platform")
    parser.add_argument("--min-discount", type=float, default=20.0)
    parser.add_argument("--category", default=None)
    parser.add_argument("--live", action="store_true", help="Actually post. Without this, just prints a preview.")
    args = parser.parse_args()

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    unknown = set(platforms) - set(ALL_PLATFORMS)
    if unknown:
        parser.error(f"Unknown platform(s): {', '.join(unknown)}. Choose from {ALL_PLATFORMS}.")

    init_db()

    with get_session() as session:
        for platform in platforms:
            if not is_configured(platform):
                logger.warning("Skipping %s — credentials not set (see .env.example)", platform)
                continue

            deals = get_candidates(session, platform, args.limit, args.min_discount, args.category)
            if not deals:
                logger.info("%s: no new eligible deals", platform)
                continue

            for deal in deals:
                caption = compose_caption(deal, platform)

                if not args.live:
                    print(f"\n[DRY RUN] {platform} — deal #{deal.id}\n{caption}\nimage: {deal.thumbnail_url}\n")
                    continue

                try:
                    result = POSTERS[platform](caption, deal.thumbnail_url)
                except (PlatformNotConfigured, PostFailed) as e:
                    logger.error("Failed to post deal #%d to %s: %s", deal.id, platform, e)
                    continue

                session.add(
                    SocialPost(
                        deal_id=deal.id,
                        platform=platform,
                        external_id=result.external_id,
                        posted_at=datetime.now(timezone.utc),
                    )
                )
                session.commit()
                logger.info("Posted deal #%d to %s (id=%s)", deal.id, platform, result.external_id)

    if not args.live:
        print("\nDry run only — nothing was posted. Re-run with --live to actually publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
