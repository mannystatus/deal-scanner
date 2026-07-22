"""
Central config for hackthedeal.com affiliate network credentials.

Nothing here is hardcoded — everything pulls from environment variables so you
can drop this straight into the Render worker env and never commit secrets to
the repo.

Set these once each network approves you. Anything left unset just means that
network's merchants stay in "pending" status and links pass through un-tagged
(see link_builder.py) instead of erroring.
"""

import os
from dataclasses import dataclass


@dataclass
class ImpactConfig:
    account_sid: str = os.getenv("IMPACT_ACCOUNT_SID", "")
    auth_token: str = os.getenv("IMPACT_AUTH_TOKEN", "")  # only needed for API calls, not deep links


@dataclass
class CJConfig:
    publisher_id: str = os.getenv("CJ_PUBLISHER_ID", "")          # aka PID/website ID
    personal_access_token: str = os.getenv("CJ_PAT", "")           # only needed for Product/Link Search API
    tracking_domain: str = os.getenv("CJ_TRACKING_DOMAIN", "www.dpbolvw.net")


@dataclass
class ShareASaleConfig:
    affiliate_id: str = os.getenv("SHAREASALE_AFFILIATE_ID", "")
    api_token: str = os.getenv("SHAREASALE_API_TOKEN", "")         # only needed for Product Datafeed API
    api_secret: str = os.getenv("SHAREASALE_API_SECRET", "")


@dataclass
class RakutenConfig:
    publisher_id: str = os.getenv("RAKUTEN_PUBLISHER_ID", "")
    client_id: str = os.getenv("RAKUTEN_CLIENT_ID", "")             # only needed for Product Search API
    client_secret: str = os.getenv("RAKUTEN_CLIENT_SECRET", "")


IMPACT = ImpactConfig()
CJ = CJConfig()
SHAREASALE = ShareASaleConfig()
RAKUTEN = RakutenConfig()
