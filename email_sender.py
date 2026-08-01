"""
Thin wrapper around Resend's REST API — no SDK dependency, just httpx
(already used everywhere else in this codebase) posting to their one
endpoint. Requires hackthedeal.com (or a subdomain) to be verified in the
Resend dashboard before FROM_EMAIL will actually send; unverified sender
domains get rejected by Resend at request time, not silently dropped.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("EMAIL_FROM", "Hack the Deal <deals@deals.hackthedeal.com>")


def is_configured() -> bool:
    return bool(RESEND_API_KEY)


def send_email(to: str, subject: str, html: str) -> bool:
    if not is_configured():
        logger.warning("RESEND_API_KEY not set — skipping send to %s", to)
        return False
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={"from": FROM_EMAIL, "to": [to], "subject": subject, "html": html},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPError as e:
        logger.error("Failed to send email to %s: %s", to, e)
        return False
