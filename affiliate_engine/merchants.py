"""
Merchant registry for hackthedeal.com.

This is the single source of truth for which network each retailer runs on,
and whether your application to that network/program is approved yet.

Workflow:
  1. Application pending -> status="pending" -> link_builder passes the raw
     destination URL through untouched (no tracking, no risk of a malformed
     link going out while you're unapproved).
  2. Approved -> flip status to "approved" and fill in program_id (Impact),
     advertiser_id (CJ), merchant_id (ShareASale/Rakuten). These IDs come
     from each network's dashboard once your application to that specific
     merchant's program is accepted (network approval and per-merchant
     program approval are two separate steps on all four networks).

Add new brands here as you apply to more programs — everything downstream
(link_builder, worker.py) reads from this list, so nothing else needs
to change.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Network(str, Enum):
    IMPACT = "impact"
    CJ = "cj"
    SHAREASALE = "shareasale"
    RAKUTEN = "rakuten"
    AMAZON = "amazon"
    NONE = "none"  # no known affiliate program


class Status(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_APPLIED = "not_applied"


@dataclass
class Merchant:
    name: str
    domain: str
    network: Network
    category: str
    status: Status = Status.NOT_APPLIED
    # Network-specific identifiers, filled in once approved:
    program_id: Optional[str] = None       # Impact: ProgramId / CampaignId
    advertiser_id: Optional[str] = None    # CJ: Advertiser ID (AID)
    merchant_id: Optional[str] = None      # ShareASale: Merchant ID / Rakuten: mid
    notes: str = ""


MERCHANTS: list[Merchant] = [
    # --- Currently pending, per your applications ---
    Merchant("Best Buy", "bestbuy.com", Network.IMPACT, "electronics", Status.PENDING),
    Merchant("Nike", "nike.com", Network.IMPACT, "athletic", Status.PENDING),
    Merchant("Adidas", "adidas.com", Network.IMPACT, "athletic", Status.PENDING),
    Merchant("REI", "rei.com", Network.IMPACT, "outdoor", Status.PENDING),
    Merchant("Adorama", "adorama.com", Network.IMPACT, "camera", Status.PENDING),

    Merchant("Nordstrom", "nordstrom.com", Network.RAKUTEN, "department", Status.PENDING),
    Merchant("Macy's", "macys.com", Network.RAKUTEN, "department", Status.PENDING),
    Merchant("Uniqlo", "uniqlo.com", Network.RAKUTEN, "fashion", Status.PENDING),
    Merchant("Levi's", "levi.com", Network.RAKUTEN, "fashion", Status.PENDING,
             notes="Verify network at approval, some fashion brands sit on CJ instead"),
    Merchant("Ralph Lauren", "ralphlauren.com", Network.RAKUTEN, "fashion", Status.PENDING),
    Merchant("MAC Cosmetics", "maccosmetics.com", Network.RAKUTEN, "beauty", Status.PENDING),
    Merchant("NYX Cosmetics", "nyxcosmetics.com", Network.RAKUTEN, "beauty", Status.PENDING),

    Merchant("J.Crew", "jcrew.com", Network.CJ, "fashion", Status.PENDING,
             notes="Verify network at approval, could be Rakuten"),

    Merchant("Homage", "homage.com", Network.SHAREASALE, "apparel", Status.PENDING,
             notes="Verify network at approval, could be Impact"),

    # --- Already live for you ---
    Merchant("Amazon", "amazon.com", Network.AMAZON, "marketplace", Status.APPROVED),

    # --- No formal affiliate program found ---
    Merchant("Micro Center", "microcenter.com", Network.NONE, "electronics", Status.NOT_APPLIED,
             notes="No open affiliate program; direct partnerships only via influencers@microcenter.com"),
    Merchant("Samy's Camera", "samys.com", Network.NONE, "camera", Status.NOT_APPLIED,
             notes="Independent regional retailer, no known affiliate network"),
    Merchant("B&H Photo", "bhphotovideo.com", Network.NONE, "camera", Status.NOT_APPLIED,
             notes="Runs its own program / Skimlinks auto-affiliation rather than a mainstream network"),
]


def get_merchant(name: str) -> Optional[Merchant]:
    for m in MERCHANTS:
        if m.name.lower() == name.lower():
            return m
    return None


def get_merchant_by_domain(hostname: str) -> Optional[Merchant]:
    """Match a URL's hostname (e.g. 'www.bestbuy.com') against a registered
    merchant's root domain (e.g. 'bestbuy.com'), including subdomains."""
    hostname = (hostname or "").lower()
    if not hostname:
        return None
    for m in MERCHANTS:
        if hostname == m.domain or hostname.endswith("." + m.domain):
            return m
    return None


def by_status(status: Status) -> list[Merchant]:
    return [m for m in MERCHANTS if m.status == status]


def by_network(network: Network) -> list[Merchant]:
    return [m for m in MERCHANTS if m.network == network]
