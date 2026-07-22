"""
Impact.com deep link builder.

Impact's redirect click format (used by every Impact-managed program,
including Best Buy, Nike, Adidas, REI, Adorama):

    https://{tracking_subdomain}/c/{AccountSID}/{ProgramId}/{AdId}?u={encoded_destination}

- AccountSID: your Impact partner account SID (same across all programs)
- ProgramId: assigned per-merchant once that specific program approves you
  (this is the `program_id` field on the Merchant record)
- AdId: the "text link" ad ID Impact auto-generates for your account inside
  that program — grab it from the program's "Ads" tab in the Impact
  dashboard once approved. Impact also lets you generate deep links via
  their web UI without needing this if you'd rather do it manually per URL.

Until `program_id` is set (i.e. status is still "pending"), this builder
just returns the destination URL unchanged so nothing breaks in the
meantime.
"""

from ..config import IMPACT
from ..merchants import Merchant, Status
from .base import DeepLinkBuilder


class ImpactLinkBuilder(DeepLinkBuilder):
    tracking_domain = "impactradius-go.com"  # replace with your assigned tracking subdomain once approved

    def build(self, merchant: Merchant, destination_url: str, sub_id: str = "") -> str:
        if merchant.status != Status.APPROVED or not merchant.program_id or not IMPACT.account_sid:
            return destination_url

        # AdId defaults to "0" (Impact auto-routes generic text-link deep links this way
        # for most programs) — override per-merchant once you have a specific Ad ID.
        ad_id = "0"
        link = (
            f"https://{self.tracking_domain}/c/{IMPACT.account_sid}/"
            f"{merchant.program_id}/{ad_id}?u={self._encode(destination_url)}"
        )
        if sub_id:
            link += f"&subId1={quote_subid(sub_id)}"
        return link


def quote_subid(sub_id: str) -> str:
    from urllib.parse import quote
    return quote(sub_id, safe="")
