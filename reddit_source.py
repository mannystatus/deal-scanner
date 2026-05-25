import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

import httpx

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
REDDIT_OAUTH_BASE = "https://oauth.reddit.com"

SELF_POST_SUBREDDITS = {"photomarket"}


def _ua() -> str:
    return os.getenv("REDDIT_USER_AGENT", "deal-scanner/0.1")


def get_oauth_token() -> Optional[str]:
    """Exchange client credentials for a bearer token. Returns None if creds not set."""
    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    try:
        r = httpx.post(
            f"{REDDIT_BASE}/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _ua()},
            timeout=15,
        )
        r.raise_for_status()
        token = r.json().get("access_token")
        logger.info("Reddit OAuth token obtained")
        return token
    except httpx.HTTPError as e:
        logger.warning("Reddit OAuth failed, falling back to anonymous: %s", e)
        return None


def fetch_subreddit(subreddit: str, limit: int = 100, token: Optional[str] = None) -> list[dict]:
    if token:
        base = REDDIT_OAUTH_BASE
        headers = {"User-Agent": _ua(), "Authorization": f"Bearer {token}"}
    else:
        base = REDDIT_BASE
        headers = {"User-Agent": _ua()}

    url = f"{base}/r/{subreddit}/new.json"
    params = {"limit": min(limit, 100), "raw_json": "1"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
    return r.json().get("data", {}).get("children", [])


def iter_posts(subreddit: str, limit: int = 100, token: Optional[str] = None) -> Iterator[dict]:
    try:
        children = fetch_subreddit(subreddit, limit=limit, token=token)
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
