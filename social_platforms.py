"""Thin wrappers around the X, Instagram, and Threads posting APIs.

Each platform needs its own developer credentials before it'll work — see
.env.example for the exact env vars and where to generate them. A poster
function raises PlatformNotConfigured if its env vars aren't set, and
PostFailed if the platform's API rejects the request.
"""

import io
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
THREADS_API_BASE = "https://graph.threads.net/v1.0"


class PlatformNotConfigured(Exception):
    pass


class PostFailed(Exception):
    pass


@dataclass
class PostResult:
    platform: str
    external_id: str


def _raise_for_graph_error(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise PostFailed(f"{resp.status_code}: {resp.text[:500]}")


# ── X (Twitter) ─────────────────────────────────────────────────────────
# developer.x.com -> create a Project + App -> User authentication settings:
# enable OAuth 1.0a with "Read and write" permissions -> Keys and tokens tab
# -> generate an Access Token & Secret for your own account.

def _x_credentials() -> tuple[str, str, str, str]:
    keys = (
        os.getenv("X_API_KEY"),
        os.getenv("X_API_SECRET"),
        os.getenv("X_ACCESS_TOKEN"),
        os.getenv("X_ACCESS_TOKEN_SECRET"),
    )
    if not all(keys):
        raise PlatformNotConfigured(
            "X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET must all be set"
        )
    return keys  # type: ignore[return-value]


def post_to_x(text: str, image_url: Optional[str] = None) -> PostResult:
    import tweepy

    api_key, api_secret, access_token, access_secret = _x_credentials()
    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
    )

    media_ids = None
    if image_url:
        # Media upload is still v1.1-only, hence the separate OAuth1UserHandler.
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
        api_v1 = tweepy.API(auth)
        image_bytes = httpx.get(image_url, timeout=15, follow_redirects=True).content
        media = api_v1.media_upload(filename="deal.jpg", file=io.BytesIO(image_bytes))
        media_ids = [media.media_id]

    try:
        resp = client.create_tweet(text=text, media_ids=media_ids)
    except tweepy.TweepyException as e:
        raise PostFailed(str(e)) from e
    return PostResult(platform="x", external_id=str(resp.data["id"]))


# ── Instagram ───────────────────────────────────────────────────────────
# developers.facebook.com -> create a Meta app (type: Business) -> add the
# "Instagram" product. Your IG account must be a Business/Creator account
# linked to a Facebook Page. Generate a long-lived access token with
# instagram_basic + instagram_content_publish + pages_show_list scopes via
# the Graph API Explorer or the Meta app dashboard, then look up your
# IG_USER_ID with GET /me/accounts -> {page-id}?fields=instagram_business_account.

def _ig_credentials() -> tuple[str, str]:
    user_id = os.getenv("IG_USER_ID")
    token = os.getenv("IG_ACCESS_TOKEN")
    if not user_id or not token:
        raise PlatformNotConfigured("IG_USER_ID and IG_ACCESS_TOKEN must both be set")
    return user_id, token


def post_to_instagram(caption: str, image_url: Optional[str] = None) -> PostResult:
    if not image_url:
        raise PostFailed("Instagram requires an image — this deal has no thumbnail_url")
    user_id, token = _ig_credentials()

    create = httpx.post(
        f"{GRAPH_API_BASE}/{user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    _raise_for_graph_error(create)
    creation_id = create.json()["id"]

    publish = httpx.post(
        f"{GRAPH_API_BASE}/{user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    _raise_for_graph_error(publish)
    return PostResult(platform="instagram", external_id=publish.json()["id"])


# ── Threads ─────────────────────────────────────────────────────────────
# Same Meta app as Instagram -> add the "Threads" product -> run the Threads
# API's own token flow to get a user access token (threads_basic +
# threads_content_publish scopes). THREADS_USER_ID comes back from that
# flow's GET /me call.

def _threads_credentials() -> tuple[str, str]:
    user_id = os.getenv("THREADS_USER_ID")
    token = os.getenv("THREADS_ACCESS_TOKEN")
    if not user_id or not token:
        raise PlatformNotConfigured("THREADS_USER_ID and THREADS_ACCESS_TOKEN must both be set")
    return user_id, token


def post_to_threads(text: str, image_url: Optional[str] = None) -> PostResult:
    user_id, token = _threads_credentials()

    payload = {"access_token": token, "text": text}
    payload["media_type"] = "IMAGE" if image_url else "TEXT"
    if image_url:
        payload["image_url"] = image_url

    create = httpx.post(f"{THREADS_API_BASE}/{user_id}/threads", data=payload, timeout=30)
    _raise_for_graph_error(create)
    creation_id = create.json()["id"]

    publish = httpx.post(
        f"{THREADS_API_BASE}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    _raise_for_graph_error(publish)
    return PostResult(platform="threads", external_id=publish.json()["id"])


POSTERS = {
    "x": post_to_x,
    "instagram": post_to_instagram,
    "threads": post_to_threads,
}

_CONFIG_CHECKS = {
    "x": _x_credentials,
    "instagram": _ig_credentials,
    "threads": _threads_credentials,
}


def is_configured(platform: str) -> bool:
    try:
        _CONFIG_CHECKS[platform]()
        return True
    except PlatformNotConfigured:
        return False
