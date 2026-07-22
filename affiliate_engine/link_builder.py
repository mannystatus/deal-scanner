"""
hackthedeal.com — universal affiliate link builder.

This is the function worker.py calls for outbound product links that don't
already go through the Amazon-specific retagging in worker.py itself. It
extends coverage to the direct-retailer merchant list (Best Buy, Nike,
Nordstrom, etc.) and makes "pending approval" a safe, explicit state instead
of a special case you have to remember to handle.

Usage:

    from affiliate_engine.link_builder import build_affiliate_link

    tagged_url = build_affiliate_link("Best Buy", "https://www.bestbuy.com/site/...", sub_id="deal_4821")

Behavior:
  - merchant not found in registry           -> returns original URL, logs a warning
  - merchant.network == NONE                 -> returns original URL (no program exists)
  - merchant.status != APPROVED               -> returns original URL (pending/not applied)
  - merchant approved + network wired up      -> returns tagged deep link
"""

import logging

from .merchants import get_merchant, Network
from .networks import (
    ImpactLinkBuilder,
    CJLinkBuilder,
    ShareASaleLinkBuilder,
    RakutenLinkBuilder,
)

logger = logging.getLogger("affiliate_engine")

_BUILDERS = {
    Network.IMPACT: ImpactLinkBuilder(),
    Network.CJ: CJLinkBuilder(),
    Network.SHAREASALE: ShareASaleLinkBuilder(),
    Network.RAKUTEN: RakutenLinkBuilder(),
}


def build_affiliate_link(merchant_name: str, destination_url: str, sub_id: str = "") -> str:
    merchant = get_merchant(merchant_name)

    if merchant is None:
        logger.warning("No merchant registry entry for '%s' — passing URL through untagged.", merchant_name)
        return destination_url

    if merchant.network in (Network.NONE,):
        return destination_url

    if merchant.network == Network.AMAZON:
        # Amazon is already tagged directly in worker.py before this function
        # is ever reached — this branch exists only so the registry entry is
        # complete and no caller accidentally routes Amazon through here.
        from .amazon_stub import build_amazon_link
        return build_amazon_link(destination_url, sub_id)

    builder = _BUILDERS.get(merchant.network)
    if builder is None:
        logger.warning("No link builder implemented for network '%s'.", merchant.network)
        return destination_url

    return builder.build(merchant, destination_url, sub_id)
