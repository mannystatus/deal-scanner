import json
import logging
import os
from typing import Optional

from pywebpush import webpush, WebPushException
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import PushSubscription
from parsers import ParsedDeal

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "mannydotco@gmail.com")

# Only notify for deals discounted at least this much — keeps volume low
# and signal high instead of pushing every new deal that lands.
NOTIFY_MIN_DISCOUNT = float(os.getenv("NOTIFY_MIN_DISCOUNT", "30"))


def is_configured() -> bool:
    return bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)


def _matching_subscriptions(session: Session, category: str) -> list[PushSubscription]:
    subs = session.execute(select(PushSubscription)).scalars().all()
    return [
        sub for sub in subs
        if not sub.categories or category in sub.categories.split(",")
    ]


def notify_new_deal(session: Session, parsed: ParsedDeal, thumbnail_url: Optional[str]) -> None:
    """Push a notification for a newly-ingested deal to every subscription
    that opted into its category, if the deal clears the discount bar."""
    if not is_configured():
        return
    if parsed.discount_pct is None or parsed.discount_pct < NOTIFY_MIN_DISCOUNT:
        return

    subs = _matching_subscriptions(session, parsed.category)
    if not subs:
        return

    payload = json.dumps({
        "title": f"{round(parsed.discount_pct)}% off — {parsed.title[:90]}",
        "body": parsed.merchant or "New deal on Hack the Deal",
        "url": parsed.affiliate_url or parsed.url,
        "icon": thumbnail_url,
    })

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
            )
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                # Browser unsubscribed or the subscription expired — stop
                # trying it instead of failing on it forever.
                session.delete(sub)
            else:
                logger.warning("Push failed for %s...: %s", sub.endpoint[:60], e)
