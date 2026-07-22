"""
ShareASale deep link builder.

ShareASale's redirect click format:

    https://www.shareasale.com/r.cfm?b={banner_id}&u={affiliate_id}&m={merchant_id}
        &urllink={encoded_destination}&afftrack={sub_id}

- affiliate_id: your ShareASale Affiliate ID — same across all programs
- merchant_id: assigned per-merchant once that program approves you
  (this is `merchant_id` on the Merchant record)
- banner_id: 0 works for a generic deep link (no specific banner creative)

Until `merchant_id` is set, this returns the destination URL unchanged.
"""

from ..config import SHAREASALE
from ..merchants import Merchant, Status
from .base import DeepLinkBuilder


class ShareASaleLinkBuilder(DeepLinkBuilder):
    def build(self, merchant: Merchant, destination_url: str, sub_id: str = "") -> str:
        if merchant.status != Status.APPROVED or not merchant.merchant_id or not SHAREASALE.affiliate_id:
            return destination_url

        link = (
            f"https://www.shareasale.com/r.cfm?b=0&u={SHAREASALE.affiliate_id}"
            f"&m={merchant.merchant_id}&urllink={self._encode(destination_url)}"
        )
        if sub_id:
            link += f"&afftrack={self._encode(sub_id)}"
        return link
