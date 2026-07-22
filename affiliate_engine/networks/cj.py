"""
CJ Affiliate (Commission Junction) deep link builder.

CJ's redirect click format:

    https://{tracking_domain}/click-{PID}-{AID}?url={encoded_destination}&sid={sub_id}

- tracking_domain: one of CJ's shared redirect domains, e.g. www.dpbolvw.net,
  www.anrdoezrs.net, www.tqlkg.net, www.kqzyfj.net, www.jdoqocy.net
  (any of these work identically — CJ assigns one as your default but they're
  interchangeable for link building)
- PID: your CJ Publisher ID (aka Website ID) — same across all programs
- AID: the Advertiser ID for that specific merchant program, assigned once
  that merchant's program approves you (this is `advertiser_id` on the
  Merchant record)

Until `advertiser_id` is set, this returns the destination URL unchanged.
"""

from ..config import CJ
from ..merchants import Merchant, Status
from .base import DeepLinkBuilder


class CJLinkBuilder(DeepLinkBuilder):
    def build(self, merchant: Merchant, destination_url: str, sub_id: str = "") -> str:
        if merchant.status != Status.APPROVED or not merchant.advertiser_id or not CJ.publisher_id:
            return destination_url

        link = (
            f"https://{CJ.tracking_domain}/click-{CJ.publisher_id}-{merchant.advertiser_id}"
            f"?url={self._encode(destination_url)}"
        )
        if sub_id:
            link += f"&sid={self._encode(sub_id)}"
        return link
