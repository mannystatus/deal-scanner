#!/usr/bin/env python3
"""
One-off cleanup for deals that were double-ingested before db.py's dedup
hash started stripping tracking-only query params (see make_hash /
_normalize_for_dedup in db.py). The clearest case: DealNews cross-posts the
same article into both its Shoes and Clothing & Accessories RSS feeds with
only the `iref` query param differing (rss-c280 vs rss-c202), which used to
produce two separate Deal rows — e.g. "Adidas Samba OG Shoes" showing up
under both /shoes/ and /fashion/ at two different permalink URLs.

Groups all current deals by the same normalized-URL hash the fixed
make_hash() now uses, and for every group with more than one row, keeps a
single "best" copy (prefers one with a thumbnail, then earliest posted_at)
and deletes the rest — including their price_history/social_posts rows,
which would otherwise violate the FK constraint. The kept row's dedup_hash
is rewritten to the normalized hash so future re-ingests correctly dedupe
against it.

Safe to re-run — a second pass finds no groups with more than one row and
does nothing.

Usage: python3 scripts/dedupe_existing_deals.py [--dry-run]
"""
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete  # noqa: E402

from db import SessionLocal, make_hash, _normalize_for_dedup  # noqa: E402
from models import Deal, PriceHistory, SocialPost  # noqa: E402


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    with SessionLocal() as session:
        deals = session.query(Deal).all()

        groups: dict[str, list[Deal]] = defaultdict(list)
        for deal in deals:
            groups[_normalize_for_dedup(deal.url)].append(deal)

        dupe_groups = {k: v for k, v in groups.items() if len(v) > 1}
        if not dupe_groups:
            print("No duplicates found.")
            return

        total_deleted = 0
        for normalized_url, group in dupe_groups.items():
            group.sort(key=lambda d: (d.thumbnail_url is None, d.posted_at))
            keeper, dupes = group[0], group[1:]
            print(f"KEEP  #{keeper.id} [{keeper.category}] {keeper.title[:70]}")
            for dupe in dupes:
                print(f"  DROP #{dupe.id} [{dupe.category}] {dupe.title[:70]}")

            if not dry_run:
                dupe_ids = [d.id for d in dupes]
                session.execute(delete(PriceHistory).where(PriceHistory.deal_id.in_(dupe_ids)))
                session.execute(delete(SocialPost).where(SocialPost.deal_id.in_(dupe_ids)))
                session.execute(delete(Deal).where(Deal.id.in_(dupe_ids)))
                keeper.dedup_hash = make_hash(keeper.url)

            total_deleted += len(dupes)

        if dry_run:
            print(f"\n[dry run] Would delete {total_deleted} duplicate rows across {len(dupe_groups)} groups.")
        else:
            session.commit()
            print(f"\nDeleted {total_deleted} duplicate rows across {len(dupe_groups)} groups.")


if __name__ == "__main__":
    main()
