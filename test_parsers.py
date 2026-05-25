import pytest
from parsers import ParsedDeal, parse_title


def test_buildapcsales_price_and_discount():
    result = parse_title(
        "[CPU] AMD Ryzen 7 7700X $249.99 (30% off) @ Amazon",
        "https://amazon.com/dp/abc",
        "buildapcsales",
    )
    assert result.deal_price == pytest.approx(249.99)
    assert result.discount_pct == pytest.approx(30.0)
    assert result.category == "computers"


def test_game_deal_with_was_price():
    result = parse_title(
        "[PC/Steam] Elden Ring $29.99 (was $59.99) @ Fanatical",
        "https://fanatical.com/game/elden-ring",
        "GameDeals",
    )
    assert result.deal_price == pytest.approx(29.99)
    assert result.original_price == pytest.approx(59.99)
    assert result.category == "gaming"


def test_apple_deal_with_reg_price():
    result = parse_title(
        "[AirPods Pro 2] $189.99 @ Best Buy (reg $249)",
        "https://bestbuy.com/product/airpods",
        "AppleDeals",
    )
    assert result.deal_price == pytest.approx(189.99)
    assert result.category == "apple"


def test_no_price_has_low_confidence():
    result = parse_title(
        "[Discussion] Looking for deals on monitors",
        "https://reddit.com/r/buildapcsales/comments/abc",
        "buildapcsales",
    )
    assert result.deal_price is None
    assert result.confidence < 0.5


def test_discount_derived_from_two_prices():
    result = parse_title(
        "[GPU] RTX 4070 $449 was $599",
        "https://amazon.com/dp/xyz",
        "buildapcsales",
    )
    assert result.deal_price == pytest.approx(449.0)
    assert result.original_price == pytest.approx(599.0)
    assert result.discount_pct is not None
    assert result.discount_pct == pytest.approx(25.04, abs=0.1)


def test_unknown_subreddit_category():
    result = parse_title("Some deal $9.99", "https://example.com", "randomsub")
    assert result.category == "other"


def test_ps5_deals_category():
    result = parse_title(
        "[PS5] Spider-Man 2 $29.99 @ PlayStation Store",
        "https://store.playstation.com/en-us/product/PPSA01404",
        "PS5Deals",
    )
    assert result.category == "gaming"
    assert result.deal_price == pytest.approx(29.99)
