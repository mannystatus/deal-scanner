import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator

import httpx

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"


def _headers() -> dict:
    ua = os.getenv("REDDIT_USER_AGENT", "deal-scanner/0.1")
    return {"User-Agent": ua}


def fetch_subreddit(subreddit: str, limit: int = 100) -> list[dict]:
    url = f"{REDDIT_BASE}/r/{subreddit}/new.json"
    params = {"limit": min(limit, 100), "raw_json": "1"}
    with httpx.Client(headers=_headers(), timeout=30, follow_redirects=True) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
    return r.json().get("data", {}).get("children", [])


# Subreddits where self posts ARE the listings (marketplace-style).
# For these, use the Reddit permalink instead of filtering the post out.
SELF_POST_SUBREDDITS = {"photomarket"}


def iter_posts(subreddit: str, limit: int = 100) -> Iterator[dict]:
    try:
        children = fetch_subreddit(subreddit, limit=limit)
    except httpx.HTTPError as e:
        logger.error("Failed to fetch r/%s: %s", subreddit, e)
        return

    allow_self = subreddit.lower() in SELF_POST_SUBREDDITS

    for post in children:
        d = post.get("data", {})
        if d.get("stickied"):
            continue
        is_self = d.get("is_self", False)
        if is_self and not allow_self:
            continue
        url = d.get("url", "")
        if is_self or not url or url.startswith("https://www.reddit.com"):
            permalink = d.get("permalink", "")
            if not permalink:
                continue
            url = f"https://www.reddit.com{permalink}"
        yield {
            "reddit_id": d.get("id", ""),
            "title": d.get("title", ""),
            "url": url,
            "posted_at": datetime.fromtimestamp(
                d.get("created_utc", time.time()), tz=timezone.utc
            ),
        }
