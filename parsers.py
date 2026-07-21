import re
from dataclasses import dataclass, field
from typing import Optional

PRICE_RE = re.compile(r'\$\s*(\d{1,5}(?:\.\d{1,2})?)')
DISCOUNT_RE = re.compile(r'(\d+)\s*%\s*off', re.IGNORECASE)
WAS_RE = re.compile(
    r'(?:was|reg(?:ular)?|orig(?:in(?:al)?)?|rrp|previously)\s*\$\s*(\d{1,5}(?:\.\d{1,2})?)',
    re.IGNORECASE,
)
# Matches "after $70 off", "$30 off" etc — these are savings amounts, not prices
DOLLAR_OFF_RE = re.compile(r'\$\s*(\d{1,5}(?:\.\d{1,2})?)\s*off', re.IGNORECASE)
AT_MERCHANT_RE = re.compile(r'[@]\s*([A-Za-z][A-Za-z0-9\s&.]{1,40}?)(?:\s*[\(\)\|,]|\s*$)')
AT_WORD_MERCHANT_RE = re.compile(r'\bat\s+([A-Z][A-Za-z0-9\s&.]{1,40}?)(?:\s*[\(\)\|,]|\s*$)')

SUBREDDIT_CATEGORIES = {
    # Reddit subreddits (legacy)
    "buildapcsales": "computers",
    "gamedeals": "gaming",
    "appledeals": "apple",
    "ps5deals": "gaming",
    "switchdeals": "gaming",
    "softwaredeals": "software",
    "pkmntcg": "trading_cards",
    "tradingcards": "trading_cards",
    "magictcg": "trading_cards",
    "photomarket": "cameras",
    "photography": "cameras",
    # RSS feed sources
    "9to5mac": "apple",
    "9to5toys": "gaming",
    "dealnews": "computers",
    "slickdeals": "other",
    "dealnews-fashion": "fashion",
    "dealnews-shoes": "shoes",
    "dealnews-beauty": "beauty",
    "dealnews-travel": "travel",
    "slickdeals-nike": "fashion",
    "slickdeals-adidas": "fashion",
    "slickdeals-levis": "fashion",
    "slickdeals-rei": "fashion",
    "slickdeals-northface": "fashion",
    "pyrodrone": "drones",
    "racedayquads": "drones",
    "dronenerds": "drones",
    "myfpvstore": "drones",
    "elegoo": "3d_printing",
    "anycubic": "3d_printing",
    "sovol": "3d_printing",
    "polymaker": "filament",
    "overture": "filament",
}

# Bracket tags like [Camera] or [Software] at the start of titles override the
# subreddit-level category when more specific.
_BRACKET_TAG_RE = re.compile(r'^\[([^\]]+)\]', re.IGNORECASE)
_TAG_CATEGORY_MAP = {
    "camera": "cameras",
    "webcam": "cameras",
    "mirrorless": "cameras",
    "dslr": "cameras",
    "lens": "cameras",
    "photography": "cameras",
    "software": "software",
    "app": "software",
    "vpn": "software",
    "antivirus": "software",
    "pokemon": "trading_cards",
    "tcg": "trading_cards",
    "mtg": "trading_cards",
    "magic": "trading_cards",
    "yugioh": "trading_cards",
    "lorcana": "trading_cards",
    "onepiece": "trading_cards",
    "drop": "trading_cards",
    "drops": "trading_cards",
}


def _category_from_title(title: str, fallback: str) -> str:
    m = _BRACKET_TAG_RE.match(title)
    if m:
        for word in re.split(r'[\s/\-]+', m.group(1).lower()):
            if word in _TAG_CATEGORY_MAP:
                return _TAG_CATEGORY_MAP[word]
    return fallback


@dataclass
class ParsedDeal:
    title: str
    url: str
    deal_price: Optional[float]
    original_price: Optional[float]
    currency: str
    discount_pct: Optional[float]
    category: str
    merchant: Optional[str]
    confidence: float
    affiliate_url: Optional[str] = field(default=None)


def _parse_prices(text: str) -> tuple[list[float], Optional[float], Optional[float]]:
    off_amounts = {float(m) for m in DOLLAR_OFF_RE.findall(text)}
    prices = [float(m) for m in PRICE_RE.findall(text) if float(m) not in off_amounts]

    discount = None
    m = DISCOUNT_RE.search(text)
    if m:
        discount = float(m.group(1))

    original = None
    m = WAS_RE.search(text)
    if m:
        original = float(m.group(1))

    return prices, discount, original


def parse_title(title: str, url: str, subreddit: str) -> ParsedDeal:
    base_category = SUBREDDIT_CATEGORIES.get(subreddit.lower(), "other")
    category = _category_from_title(title, base_category)
    prices, discount, original_price = _parse_prices(title)

    deal_price = prices[0] if prices else None

    # Two prices with no explicit "was" — assume lower = deal, higher = original
    if len(prices) >= 2 and original_price is None:
        deal_price = min(prices[:2])
        original_price = max(prices[:2])

    # Derive discount from prices if not explicit
    if deal_price and original_price and discount is None and original_price > deal_price:
        discount = round((1 - deal_price / original_price) * 100, 1)

    merchant = None
    m = AT_MERCHANT_RE.search(title) or AT_WORD_MERCHANT_RE.search(title)
    if m:
        merchant = m.group(1).strip()

    confidence = 0.3
    if deal_price is not None:
        confidence += 0.3
    if discount is not None:
        confidence += 0.2
    if original_price is not None:
        confidence += 0.1
    if merchant is not None:
        confidence += 0.1

    return ParsedDeal(
        title=title,
        url=url,
        deal_price=deal_price,
        original_price=original_price,
        currency="USD",
        discount_pct=discount,
        category=category,
        merchant=merchant,
        confidence=min(confidence, 1.0),
    )
