"""
One-off backfill: resolve the real Amazon destination for existing deals
and retag it with our affiliate tag.

Most stored `url` values are the *aggregator's* article page (slickdeals.net,
dealnews.com), not Amazon directly — the actual Amazon link only shows up
after fetching that page and following its outbound click-tracker. This
reuses worker.py's fetch_page_extras (the same logic used for new deals) to
do exactly that, for every existing deal that's missing an affiliate_url.

Only sources with a known resolution path are attempted:
  - dealnews*    (data-href click.html -> JS redirect -> Amazon)
  - slickdeals*  (dealDetailsOutclickButton -> real 302 redirect -> Amazon)
9to5toys/9to5mac are skipped: their articles often embed several Amazon
links with different tags for different products in one post, so picking
"the" link risks tagging the wrong product. Direct amazon.* urls (any
source) are always retagged since that's an unambiguous swap.

Connects using DATABASE_URL from the environment, same as worker.py/api.py.

Usage:
    python backfill_amazon_affiliate.py            # dry run, prints what would change
    python backfill_amazon_affiliate.py --apply     # actually writes the updates
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from sqlalchemy import select, or_

from db import SessionLocal, DATABASE_URL
from models import Deal
from worker import fetch_page_extras, _is_amazon_host

_RESOLVABLE_PREFIXES = ("dealnews", "slickdeals")
_CONCURRENCY = 3


def _eligible(deal: Deal) -> bool:
    if deal.affiliate_url:
        return False
    if _is_amazon_host(deal.url):
        return True
    return deal.source.startswith(_RESOLVABLE_PREFIXES)


def main() -> None:
    apply = "--apply" in sys.argv
    parsed = urlparse(DATABASE_URL)
    print(f"Target DB: {parsed.scheme}://{parsed.hostname or '(local)'}{parsed.path}")

    session = SessionLocal()
    try:
        candidates = session.execute(
            select(Deal).where(
                Deal.affiliate_url.is_(None),
                or_(
                    Deal.url.ilike("%amazon%"),
                    *[Deal.source.like(f"{p}%") for p in _RESOLVABLE_PREFIXES],
                ),
            )
        ).scalars().all()
        candidates = [d for d in candidates if _eligible(d)]
        print(f"Checking {len(candidates)} candidate deal(s)...\n")

        changed = 0
        checked = 0

        def resolve(deal: Deal):
            return deal, fetch_page_extras(deal.url, deal.source)

        with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
            futures = [pool.submit(resolve, d) for d in candidates]
            for future in as_completed(futures):
                deal, (thumbnail_url, affiliate_url) = future.result()
                checked += 1
                if checked % 25 == 0:
                    print(f"  ...{checked}/{len(candidates)} checked")
                if not affiliate_url:
                    continue
                changed += 1
                print(f"[{deal.id}] {deal.source} — {deal.title[:55]!r}")
                print(f"    -> {affiliate_url}")
                if apply:
                    deal.affiliate_url = affiliate_url
                    if thumbnail_url and not deal.thumbnail_url:
                        deal.thumbnail_url = thumbnail_url

        if apply:
            session.commit()
            print(f"\nUpdated {changed} of {checked} checked deal(s).")
        else:
            print(f"\nDry run — {changed} of {checked} checked deal(s) would be updated. Re-run with --apply to write.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
