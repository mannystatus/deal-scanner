"""
Rakuten Advertising deep link builder.

Rakuten's redirect click format (still branded "linksynergy" from its
LinkShare days, this is their standard deep-link endpoint):

    https://click.linksynergy.com/deeplink?id={PublisherID}&mid={MerchantID}
        &murl={encoded_destination}

- PublisherID: your Rakuten Publisher ID — same across all programs
- MerchantID (mid): assigned per-merchant once that program approves you
  (this is `merchant_id` on the Merchant record — this covers Nordstrom,
  Macy's, Uniqlo, Levi's, Ralph Lauren, MAC, NYX once each program approves)

Rakuten also supports a subId param for tracking (u1).

Until `merchant_id` is set, this returns the destination URL unchanged.
"""

from ..config import RAKUTEN
from ..merchants import Merchant, Status
from .base import DeepLinkBuilder


class RakutenLinkBuilder(DeepLinkBuilder):
    def build(self, merchant: Merchant, destination_url: str, sub_id: str = "") -> str:
        if merchant.status != Status.APPROVED or not merchant.merchant_id or not RAKUTEN.publisher_id:
            return destination_url

        link = (
            f"https://click.linksynergy.com/deeplink?id={RAKUTEN.publisher_id}"
            f"&mid={merchant.merchant_id}&murl={self._encode(destination_url)}"
        )
        if sub_id:
            link += f"&u1={self._encode(sub_id)}"
        return link
