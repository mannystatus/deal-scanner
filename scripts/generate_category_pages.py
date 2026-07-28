#!/usr/bin/env python3
"""
Generates the site's static, crawlable surface from live deal data:

  1. frontend/<slug>/index.html for every category route (Cloudflare Pages
     serves this at both /<slug> and /<slug>/ automatically), and
     frontend/index.html for the homepage — same per-category
     <title>/meta/canonical/OG/BreadcrumbList swap this script always did,
     PLUS real deal cards + an ItemList JSON-LD block rendered into the page
     between the `<!-- PRERENDER:START/END -->` markers inside `<div
     id="root">`. The React app is untouched: it replaces everything inside
     #root the instant it mounts (see frontend/index.html's module script),
     so this is purely a fallback snapshot for crawlers and no-JS visitors —
     real users see it for a flash at most.
  2. frontend/deal/<id>-<slug>/index.html — a standalone permalink page per
     active deal (Product + BreadcrumbList JSON-LD, no React/JS needed),
     so individual products are indexable and can rank on their own, not
     just the category they live in. Regenerated from scratch every run —
     deals that have aged out (see MAX_DEAL_AGE_DAYS) get their page deleted
     rather than left around as stale/expired thin content.
  3. frontend/sitemap.xml — every static page, category page, and active
     deal permalink, with real lastmod dates.

Run after every ingest (see .github/workflows/ingest.yml) so the static
snapshot is never more than a day stale. Requires DATABASE_URL to point at
the same database the API reads from; falls back to local sqlite deals.db
otherwise (see db.py).

Usage: python3 scripts/generate_category_pages.py
"""
import html
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import desc, or_, select  # noqa: E402

from db import SessionLocal, PRICE_TRACKED_CATEGORIES  # noqa: E402
from models import Deal  # noqa: E402

TEMPLATE_PATH = ROOT / "frontend" / "index.html"
BASE_URL = "https://www.hackthedeal.com"

# Keep these two in sync with the same-named constants in api.py — this
# script's prerendered snapshot must only ever show deals the live API
# would actually still serve, or crawlers/users would see dead-looking
# content that the real feed has already dropped.
MAX_DEAL_AGE_DAYS = 30
BLOCKED_SOURCES = {"bensbargains"}

DEALS_PER_PAGE = 60

# Keep in sync with CATEGORY_COPY in frontend/index.html.
# Real, category-specific buying-guide copy — not generated from deal data,
# not filler. Rendered as a second paragraph below the hero description on
# every category page (see render_prerender_block) and mirrored in
# frontend/index.html's client-side CATEGORY_COPY so real browser users see
# the same thing, not just crawlers hitting the prerendered snapshot.
CATEGORIES = {
    "amazon_finds": {
        "h1": "Amazon Finds We Love",
        "description": "Curated Amazon picks across tech, home, trading cards, fashion, and more — hand-picked finds from top-rated products and customer favorites.",
        "guide": "These aren't pulled from a deal feed — we hand-pick them from Amazon's own bestseller and highly-rated listings in categories we already cover, so what's here is stuff we'd actually recommend, not just whatever happens to be discounted this week.",
    },
    "black_friday": {
        "h1": "Best Black Friday & Cyber Monday Deals",
        "description": "Live Black Friday and Cyber Monday price drops across every category — tech, gaming, fashion, and more. Hack the Deal tracks Black Friday deals from top retailers continuously.",
        "guide": "Retailers start \"Black Friday\" pricing weeks before the actual date and often re-run the same discount at Christmas, so we track this page by what's actually cheaper right now, not by the calendar. Compare the \"was\" price against what you've seen the item sell for over the past month before assuming it's a real drop.",
    },
    "christmas": {
        "h1": "Best Christmas & Holiday Deals",
        "description": "Live holiday price drops and gift deals across every category. Hack the Deal tracks Christmas deals from top retailers continuously.",
        "guide": "Holiday listings lean toward gifts and bundles worth buying ahead rather than waiting for a lower price closer to the date — shipping cutoffs matter more here than squeezing out another few dollars of discount. Check the posted date on each card; holiday inventory moves fast and older listings can sell out.",
    },
    "back_to_school": {
        "h1": "Best Back to School Deals",
        "description": "Live price drops on laptops, school supplies, and dorm essentials. Hack the Deal tracks back to school deals from top retailers continuously.",
        "guide": "Laptop and school-supply deals cluster in late summer, but the biggest cuts on prior-generation laptops usually show up right after a manufacturer's new model launches, not during the official back-to-school sales window — worth checking current-gen specs before assuming older is worse.",
    },
    "computers": {
        "h1": "Best Computer & Laptop Deals Today",
        "description": "Live price drops on laptops, desktops, monitors, and PC components. Hack the Deal tracks computer deals from top retailers continuously.",
        "guide": "A discounted laptop or desktop is only a good deal if the specs still hold up — check RAM, storage type (SSD vs. eMMC), and GPU generation before the price. We track drops on full builds and individual components like monitors and storage, since a $40 monitor deal is easy to miss buried in a laptop-heavy feed.",
    },
    "gaming": {
        "h1": "Best Gaming Deals Today",
        "description": "Live price drops on gaming consoles, PC games, accessories, and peripherals. Hack the Deal tracks gaming deals from top retailers continuously.",
        "guide": "Console bundle \"deals\" sometimes cost more than buying the console and games separately at their own sale prices — the discount shown is off the bundle's own list price, so it's worth doing that comparison yourself. Digital game sales move fast and can end same-day, so the posted date matters more here than almost anywhere else.",
    },
    "apple": {
        "h1": "Best Apple & iPhone Deals Today",
        "description": "Live price drops on iPhone, iPad, Mac, AirPods, and Apple Watch. Hack the Deal tracks Apple deals from top retailers continuously.",
        "guide": "Apple rarely discounts directly, so real price drops come from authorized resellers clearing older or refurbished stock — check whether a listing is new, renewed, or open-box before assuming it's the same as buying from Apple. The best AirPods and Watch discounts tend to land around a new product launch, when retailers clear the outgoing model.",
    },
    "cameras": {
        "h1": "Best Camera & Photography Deals Today",
        "description": "Live price drops on cameras, lenses, drones, and photography gear. Hack the Deal tracks camera deals from top retailers continuously.",
        "guide": "Camera body prices swing hard around a manufacturer's next release announcement — a body that's been out 18+ months is where the real discounts show up, not brand-new releases. Watch lens deals separately from bodies; a slower but well-reviewed lens on sale can outperform a kit lens at full price.",
    },
    "software": {
        "h1": "Best Software Deals Today",
        "description": "Live price drops on software licenses, subscriptions, and digital tools. Hack the Deal tracks software deals from top retailers continuously.",
        "guide": "A perpetual license (buy once, own it) is usually a better long-term deal than a discounted first-year subscription that renews at full price — read the fine print on whether a \"deal\" price is one-time or an intro rate. We track individual licenses and bundle sites separately, since bundles can hide a couple of genuinely useful tools among filler.",
    },
    "streaming": {
        "h1": "Best Streaming & Digital Media Deals Today",
        "description": "Live price drops on iTunes and Google Play movies, TV shows, and eBooks, plus streaming service offers like Hulu and YouTube TV. Hack the Deal tracks streaming deals from top retailers continuously.",
        "guide": "Digital movie and show sales tend to track physical media release windows — a title usually gets its steepest digital discount 3-6 months after release, then again around its one-year mark. Streaming service promo pricing almost always locks you into an annual plan; check the cancellation terms before committing for the discount alone.",
    },
    "trading_cards": {
        "h1": "Best Trading Card Deals Today",
        "description": "Live price drops on trading card boxes, packs, and singles across Pokémon, sports, and TCGs. Hack the Deal tracks trading card deals continuously.",
        "guide": "Sealed product (boxes, packs) pricing is volatile and tied to secondary-market demand for what's inside, not retail MSRP — a \"deal\" on a box can still be above what it sold for a year ago if the set's grown popular. We track boxes and singles separately, since a single-card deal lives or dies on the exact card, not the set.",
    },
    "fashion": {
        "h1": "Best Fashion & Clothing Deals Today",
        "description": "Live price drops on clothing, shoes, and accessories for men and women. Hack the Deal tracks fashion deals from top retailers continuously.",
        "guide": "End-of-season clearance (winter coats in February, sandals in September) is consistently where the deepest cuts show up versus mid-season \"sale\" pricing — worth buying a size ahead if you can. Sizing runs inconsistently across brands even at the same retailer, so check the specific brand's size chart rather than assuming your usual size.",
    },
    "beauty": {
        "h1": "Best Beauty & Health Deals Today",
        "description": "Live price drops on makeup, skincare, haircare, and health essentials. Hack the Deal tracks beauty deals from top retailers continuously.",
        "guide": "Worth checking expiration/batch dates on steep skincare or haircare discounts, especially for niche or discontinued shades — a deep cut sometimes means a brand is clearing a line that's being replaced. Bundle sets can genuinely save money or just pad the price around one desirable item; check what the core product costs alone first.",
    },
    "shoes": {
        "h1": "Best Shoe Deals Today",
        "description": "Live price drops on sneakers, boots, and shoes for men, women, and kids. Hack the Deal tracks shoe deals from top retailers continuously.",
        "guide": "Sneaker resale and collab drops behave differently from ordinary clearance — a \"deal\" on a hyped release can still be inflated over retail if it's coming from a reseller rather than the brand directly. For everyday shoes, checking whether a discontinued colorway is the only reason for the discount tells you whether it'll still be around next week.",
    },
    "travel": {
        "h1": "Best Travel Deals Today",
        "description": "Live price drops on flights, hotels, cruises, and travel gear. Hack the Deal tracks travel deals from top retailers continuously.",
        "guide": "Flight and hotel deals expire fast and are seat/room-count limited, so the posted date matters more here than in almost any other category — a fare from three days ago is very likely gone already. Always re-check the total price (bags, resort fees) before booking, since the headline number rarely includes everything.",
    },
    "drones": {
        "h1": "Best Drone & FPV Parts Deals Today",
        "description": "Live price drops on drones, FPV parts, batteries, motors, and accessories straight from vendors like Pyrodrone and RaceDayQuads. Hack the Deal tracks drone deals continuously.",
        "guide": "FPV parts pricing is tightly tied to a handful of vendors clearing older frame/motor generations ahead of a new release — checking a part's release date against current-gen specs tells you whether a discount is a real bargain or just outdated stock. Batteries and props are consumables worth stocking up on during a sale; frames and flight controllers are worth comparing specs on first.",
    },
    "3d_printing": {
        "h1": "Best 3D Printer Deals Today",
        "description": "Live price drops on 3D printers and supplies straight from vendors like Elegoo, Anycubic, and Sovol. Hack the Deal tracks 3D printing deals continuously.",
        "guide": "Printer deals cluster around a brand clearing a model right before — or right after — its successor launches; check whether a discounted printer is still receiving firmware updates before assuming last-gen is a bargain. Bundled filament or resin is a nice-to-have, not the reason to buy — price the printer on its own first.",
    },
    "filament": {
        "h1": "Best 3D Printer Filament Deals Today",
        "description": "Live price drops on PLA, PETG, ABS, and specialty filament straight from vendors like Bambu Lab, Overture, and Polymaker. Hack the Deal tracks filament deals continuously.",
        "guide": "Filament pricing per kilogram varies a lot by material — PLA is cheapest, specialty resins and carbon-fiber blends cost more — so compare a \"deal\" against that material's typical price, not filament in general. Buying multiple spools during a sale only pays off if you're actually printing enough to use them before they degrade; PLA and PETG store better long-term than ABS.",
    },
}

HOME_COPY = {
    "h1": "Live Deals on Tech, Gaming, Apple & Daily Essentials",
    "description": "Find the best online deals, discounts, and price drops on tech, gaming, Apple, cameras, trading cards, and daily essentials. Hack the Deal scans live deals from top retailers so you never miss a sale.",
    "guide": "New listings come from Reddit deal communities, retailer RSS feeds, and vendors' own sale pages, then get scored on how clearly the post states a price, discount, and merchant before anything is published — not on how big the \"was\" price looks. Every card links to a permalink with the price we saw and when we saw it, so you can judge a deal yourself before clicking through.",
}

# Short nav-style labels — keep in sync with the CATEGORIES array in
# frontend/index.html. Used for breadcrumbs and internal-link anchor text.
CATEGORY_LABELS = {
    "amazon_finds": "Amazon Finds",
    "black_friday": "Black Friday",
    "christmas": "Christmas",
    "back_to_school": "Back to School",
    "computers": "Computers",
    "gaming": "Gaming",
    "apple": "Apple",
    "cameras": "Cameras",
    "software": "Software",
    "streaming": "Streaming",
    "trading_cards": "Trading Cards",
    "fashion": "Fashion",
    "beauty": "Beauty",
    "shoes": "Shoes",
    "travel": "Travel",
    "drones": "Drones",
    "3d_printing": "3D Printing",
    "filament": "3D Filament",
}

# Cross-cutting keyword filters layered on top of a deal's real category —
# keep in sync with SEASONAL_KEYWORDS in frontend/index.html. A deal never
# actually has category="black_friday" etc.; these pages match by title.
SEASONAL_KEYWORDS = {
    "black_friday": ["black friday", "cyber monday", "doorbuster"],
    "christmas": ["christmas", "xmas", "holiday gift", "holiday deal", "holiday sale"],
    "back_to_school": ["back to school", "back-to-school", "school supplies"],
}

# amazon_finds isn't backed by the deals table at all — it's a hardcoded
# curated affiliate list (AffiliateSection in frontend/index.html) — so
# there's nothing in the DB to prerender for it. Left with an empty
# #root, same as before this script prerendered anything.
NO_PRERENDER_CATEGORIES = {"amazon_finds"}

HERO_ICON_SVG = (
    '<svg viewBox="0 0 88 88">'
    '<circle cx="44" cy="44" r="44" fill="var(--icon-bg)"></circle>'
    '<path d="M14 78 Q44 30 74 78 Z" fill="#2a2d3f"></path>'
    '<circle cx="44" cy="50" r="20" fill="#414868"></circle>'
    '<rect x="32" y="45" width="24" height="10" rx="2" fill="#0a0c12"></rect>'
    '<path d="M74 58 L90 42 L98 58 L90 74 L74 58Z" fill="#f7768e"></path>'
    '<text x="90" y="62" font-family="sans-serif" font-size="9" fill="#3b0f18" text-anchor="middle">%</text>'
    "</svg>"
)

DISCLOSURE_AND_CONSENT_HTML = """
    <!-- Amazon Associates disclosure — static markup, guaranteed visible
         immediately and to non-JS crawlers. -->
    <div class="disclosure-bar">
      This site contains affiliate links, including as an Amazon Associate — we earn from qualifying purchases at no extra cost to you.
    </div>

    <div id="consent-overlay" class="consent-overlay" style="display: none;">
      <div class="consent-box">
        <div class="consent-text">
          <p class="consent-title">🍪 We use cookies</p>
          <p>
            This site uses cookies to measure site performance and improve your experience.
            By clicking OK, you accept our use of cookies as described in our
            <a href="/privacy.html">Privacy Policy</a>.
          </p>
        </div>
        <button id="consent-ok" type="button">OK</button>
      </div>
    </div>
    <script>
      (function () {
        if (localStorage.getItem('htd_consent_v1') !== 'granted') {
          document.getElementById('consent-overlay').style.display = 'flex';
        }
        document.getElementById('consent-ok').addEventListener('click', function () {
          localStorage.setItem('htd_consent_v1', 'granted');
          document.getElementById('consent-overlay').style.display = 'none';
          gtag('consent', 'update', {
            'ad_storage': 'granted',
            'ad_user_data': 'granted',
            'ad_personalization': 'granted',
            'analytics_storage': 'granted'
          });
        });
      })();
    </script>
"""


# ── Helpers ──────────────────────────────────────────────────────────────

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].rstrip("-") or "deal"


def deal_permalink(deal: Deal) -> str:
    # Trailing slash matters: this site is hosted on Render (render.yaml),
    # whose static-site routing has no directory-index auto-resolution —
    # only a catch-all `/* -> /index.html` SPA fallback. A path like
    # /deal/123-foo (no slash) never matches the literal
    # frontend/deal/123-foo/index.html file, so it falls through to the
    # catch-all and silently serves the homepage instead. /deal/123-foo/
    # (trailing slash) matches the directory's index.html directly and
    # works. Same reasoning applies everywhere a category slug builds a URL
    # below.
    return f"/deal/{deal.id}-{slugify(deal.title)}/"


def format_price(value, currency: str = "USD") -> str | None:
    if value is None:
        return None
    amount = f"{float(value):,.2f}"
    return f"${amount}" if currency == "USD" else f"{amount} {currency}"


def format_date(dt: datetime) -> str:
    return dt.strftime("%b %-d, %Y")


def outbound_rel(deal: Deal) -> str:
    # "sponsored" tells Google this is a paid/affiliate link, not an
    # editorial endorsement passing PageRank — required whenever
    # affiliate_url (a monetized link) is what's actually being linked to.
    return "sponsored noopener noreferrer" if deal.affiliate_url else "noopener noreferrer"


# ── Data access ──────────────────────────────────────────────────────────

def _base_query():
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_DEAL_AGE_DAYS)
    return select(Deal).where(
        Deal.confidence >= 0.5,
        or_(Deal.posted_at >= cutoff, Deal.category.in_(PRICE_TRACKED_CATEGORIES)),
        Deal.source.notin_(BLOCKED_SOURCES),
    )


def fetch_home_deals(session, limit: int = DEALS_PER_PAGE) -> list[Deal]:
    q = _base_query().where(Deal.category.notin_(PRICE_TRACKED_CATEGORIES))
    q = q.order_by(desc(Deal.posted_at)).limit(limit)
    return list(session.execute(q).scalars().all())


def fetch_category_deals(session, slug: str, limit: int = DEALS_PER_PAGE) -> list[Deal]:
    if slug in SEASONAL_KEYWORDS:
        terms = SEASONAL_KEYWORDS[slug]
        q = _base_query().where(or_(*[Deal.title.ilike(f"%{t}%") for t in terms]))
    else:
        q = _base_query().where(Deal.category == slug)
    q = q.order_by(desc(Deal.posted_at)).limit(limit)
    return list(session.execute(q).scalars().all())


def fetch_all_active_deals(session) -> list[Deal]:
    q = _base_query().order_by(desc(Deal.posted_at))
    return list(session.execute(q).scalars().all())


# ── Rendering: deal cards + category/home prerender block ───────────────

def render_deal_card(deal: Deal) -> str:
    if deal.thumbnail_url:
        image_html = (
            f'<img src="{esc(deal.thumbnail_url)}" alt="{esc(deal.title)}" loading="lazy" />'
        )
    else:
        image_html = '<div class="deal-card-icon-fallback"></div>'

    discount_html = (
        f'<span class="discount-badge">{round(deal.discount_pct)}% off</span>'
        if deal.discount_pct
        else ""
    )
    price = format_price(deal.deal_price, deal.currency)
    original = format_price(deal.original_price, deal.currency)
    price_html = (
        f'<span class="price-current">{esc(price)}</span>'
        if price
        else '<span style="font-size:13px;color:var(--muted)">See deal</span>'
    )
    if original:
        price_html += f'<span class="price-original">{esc(original)}</span>'

    # Points at the internal permalink page, not straight at the affiliate
    # link — crawlers get a real page to index and follow; the live React
    # app replaces this the instant it mounts and links straight to
    # affiliate_url/url instead, so real users' click-through is unchanged.
    return f"""<a href="{esc(deal_permalink(deal))}" class="deal-card">
      {image_html}
      <div class="deal-card-body">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
          <span class="cat-chip">{esc(deal.category)}</span>
          {discount_html}
        </div>
        <p class="deal-title">{esc(deal.title)}</p>
        <div style="display:flex;align-items:baseline;gap:8px">
          {price_html}
        </div>
        <div class="deal-meta">
          <span>{esc(deal.merchant or deal.source)}</span>
          <span>{esc(format_date(deal.posted_at))}</span>
        </div>
      </div>
    </a>"""


def render_static_footer() -> str:
    links = "".join(
        f'<a href="/{slug}/">{esc(label if slug == "amazon_finds" else label + " Deals")}</a>'
        for slug, label in CATEGORY_LABELS.items()
    )
    return f"""<footer class="site-footer">
      <div style="max-width:1152px;margin:0 auto;padding:16px 16px 0;display:flex;flex-wrap:wrap;gap:14px;font-size:12px">
        {links}
      </div>
      <div style="max-width:1152px;margin:0 auto;padding:12px 16px 20px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;font-size:12px">
        <span>© Hack the Deal {date.today().year}. <strong>This site contains affiliate links, including as an Amazon Associate — we earn from qualifying purchases.</strong></span>
        <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
          <a href="/about.html">How We Find Deals</a>
          <a href="/contact.html" class="footer-contact-link">Partner With Us</a>
          <a href="/privacy.html">Privacy Policy</a>
          <a href="/terms.html">Terms of Use</a>
        </div>
      </div>
    </footer>"""


def render_prerender_block(h1: str, description: str, guide: str, deals: list[Deal]) -> str:
    if deals:
        cards = "".join(render_deal_card(d) for d in deals)
        grid = (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px">'
            f"{cards}</div>"
        )
    else:
        grid = '<p style="text-align:center;padding:60px 0;color:var(--muted)">No deals match right now — check back soon.</p>'

    # A second, longer paragraph of real buying-guide copy (see CATEGORIES/
    # HOME_COPY above) — not another restatement of "we track deals", actual
    # category-specific advice — plus a link to /about.html so both crawlers
    # and readers can find the full sourcing/verification writeup from every
    # single page, not just the footer.
    guide_html = (
        f'<p class="hero-guide" style="max-width:640px;margin-top:10px;font-size:13px;line-height:1.6;color:var(--muted)">'
        f'{esc(guide)} <a href="/about.html">How we find and verify deals →</a></p>'
        if guide
        else ""
    )

    return f"""
      <section class="hero">
        <div class="hero-icon">{HERO_ICON_SVG}</div>
        <div>
          <p class="hero-eyebrow">$ curl hackthedeal.com --live</p>
          <h1 class="hero-title">{esc(h1)}</h1>
          <p class="hero-sub">{esc(description)}</p>
          {guide_html}
        </div>
      </section>
      <main style="max-width:1152px;margin:0 auto;padding:8px 16px 40px">
        <div class="section-title-bar"><span class="section-label">Latest Deals</span></div>
        {grid}
      </main>
      {render_static_footer()}
    """


# ── JSON-LD ──────────────────────────────────────────────────────────────

def build_itemlist_jsonld(deals: list[Deal], list_name: str) -> str:
    if not deals:
        return ""
    items = ",\n".join(
        f'{{ "@type": "ListItem", "position": {i}, "name": {_json_str(d.title)}, "url": "{BASE_URL}{deal_permalink(d)}" }}'
        for i, d in enumerate(deals, start=1)
    )
    return f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "ItemList",
      "name": {_json_str(list_name)},
      "itemListElement": [
{items}
      ]
    }}
    </script>
"""


def _json_str(s: str) -> str:
    # Deal titles come from Reddit/RSS sources — escape "<" so a title
    # containing literal "</script>" text can't break out of the JSON-LD
    # <script> block it's embedded in.
    return json.dumps(s).replace("<", "\\u003c")


def build_deal_product_jsonld(deal: Deal) -> str:
    price = deal.deal_price
    offers = ""
    if price is not None:
        valid_until = (deal.posted_at + timedelta(days=MAX_DEAL_AGE_DAYS)).date().isoformat()
        offers = f""",
      "offers": {{
        "@type": "Offer",
        "url": "{BASE_URL}{deal_permalink(deal)}",
        "priceCurrency": {_json_str(deal.currency)},
        "price": "{price}",
        "priceValidUntil": "{valid_until}"
      }}"""
    image = f',\n      "image": {_json_str(deal.thumbnail_url)}' if deal.thumbnail_url else ""
    return f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": {_json_str(deal.title)},
      "url": "{BASE_URL}{deal_permalink(deal)}"{image}{offers}
    }}
    </script>
"""


def build_breadcrumb_jsonld(items: list[tuple[str, str]]) -> str:
    elements = ",\n".join(
        f'{{ "@type": "ListItem", "position": {i}, "name": {_json_str(name)}, "item": "{url}" }}'
        for i, (name, url) in enumerate(items, start=1)
    )
    return f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      "itemListElement": [
{elements}
      ]
    }}
    </script>
"""


# ── Category / home page assembly ────────────────────────────────────────

def swap_head_meta(template: str, title: str, description: str, url: str) -> str:
    # Replacement strings come from re.sub, which treats backslashes
    # specially (\1 group refs etc.) — deal titles are attacker/source
    # controlled (Reddit/RSS), so a stray backslash could corrupt the page.
    # Wrapping every replacement in a lambda sidesteps that entirely.
    html_out = template
    html_out = re.sub(r"<title>.*?</title>", lambda m: f"<title>{esc(title)}</title>", html_out, count=1)
    html_out = re.sub(
        r'<meta name="description" content="[^"]*" />',
        lambda m: f'<meta name="description" content="{esc(description)}" />',
        html_out, count=1,
    )
    html_out = re.sub(
        r'<link rel="canonical" href="[^"]*" />',
        lambda m: f'<link rel="canonical" href="{esc(url)}" />',
        html_out, count=1,
    )
    html_out = re.sub(
        r'<meta property="og:url" content="[^"]*" />',
        lambda m: f'<meta property="og:url" content="{esc(url)}" />',
        html_out, count=1,
    )
    html_out = re.sub(
        r'<meta property="og:title" content="[^"]*" />',
        lambda m: f'<meta property="og:title" content="{esc(title)}" />',
        html_out, count=1,
    )
    html_out = re.sub(
        r'<meta property="og:description" content="[^"]*" />',
        lambda m: f'<meta property="og:description" content="{esc(description)}" />',
        html_out, count=1,
    )
    html_out = re.sub(
        r'<meta name="twitter:title" content="[^"]*" />',
        lambda m: f'<meta name="twitter:title" content="{esc(title)}" />',
        html_out, count=1,
    )
    html_out = re.sub(
        r'<meta name="twitter:description" content="[^"]*" />',
        lambda m: f'<meta name="twitter:description" content="{esc(description)}" />',
        html_out, count=1,
    )
    return html_out


def inject_prerender(template: str, block: str) -> str:
    # block embeds deal titles, which can contain literal backslashes —
    # a lambda replacement (see swap_head_meta) avoids re.sub treating
    # those as group-reference escapes.
    return re.sub(
        r"<!-- PRERENDER:START -->.*?<!-- PRERENDER:END -->",
        lambda m: f"<!-- PRERENDER:START -->{block}<!-- PRERENDER:END -->",
        template,
        count=1,
        flags=re.DOTALL,
    )


def inject_seo_block(template: str, snippet: str) -> str:
    # Marker-based replace (not append) — same idempotency requirement as
    # inject_prerender. Without this, re-running the generator against a
    # frontend/index.html that already has a prior run's JSON-LD baked in
    # (it's both the read template and the homepage's write target) would
    # stack up duplicate/wrong structured data on every run.
    return re.sub(
        r"<!-- SEO:START -->.*?<!-- SEO:END -->",
        lambda m: f"<!-- SEO:START -->{snippet}<!-- SEO:END -->",
        template,
        count=1,
        flags=re.DOTALL,
    )


def build_page(template: str, slug: str, h1: str, description: str, guide: str, deals: list[Deal]) -> str:
    url = f"{BASE_URL}/{slug}/" if slug else f"{BASE_URL}/"
    title = f"{h1} – Live Price Drops | Hack the Deal" if slug else f"{h1} | Hack the Deal"

    page = swap_head_meta(template, title, description, url)

    seo_snippet = ""
    if slug:
        breadcrumb_items = [("Home", f"{BASE_URL}/"), (h1, url)]
        seo_snippet += build_breadcrumb_jsonld(breadcrumb_items)
    if slug not in NO_PRERENDER_CATEGORIES:
        seo_snippet += build_itemlist_jsonld(deals, h1)
    page = inject_seo_block(page, seo_snippet)

    # Always call inject_prerender, even for amazon_finds (empty block) —
    # `template` is both the read source and (for the homepage) the write
    # target, so skipping this would leave whatever was between the
    # markers from a *previous* run's output in place instead of resetting
    # it, silently leaking that run's content into this page.
    prerender_html = "" if slug in NO_PRERENDER_CATEGORIES else render_prerender_block(h1, description, guide, deals)
    page = inject_prerender(page, prerender_html)

    return page


# ── Deal permalink pages ─────────────────────────────────────────────────

def build_deal_page(head_template: str, deal: Deal) -> str:
    permalink = deal_permalink(deal)
    url = f"{BASE_URL}{permalink}"
    label = CATEGORY_LABELS.get(deal.category)
    title = f"{deal.title[:70]} — {round(deal.discount_pct)}% Off" if deal.discount_pct else deal.title[:90]
    title = f"{title} | Hack the Deal"
    description = (
        f"{deal.title} at {deal.merchant or deal.source}"
        + (f" — {format_price(deal.deal_price, deal.currency)}" if deal.deal_price is not None else "")
        + ". Tracked live by Hack the Deal."
    )

    head = swap_head_meta(head_template, title, description[:300], url)
    # Individual deal permalinks are thin by nature — a scraped title, a
    # price, and one outbound link — so they're excluded from indexing and
    # from the sitemap (see build_sitemap). They stay live and linked (the
    # deal cards on category pages still point here, and "follow" keeps
    # crawl equity flowing to the category pages), just not asked to rank
    # or count toward the site's indexed-content quality on their own.
    head = head.replace(
        '<meta name="robots" content="index, follow" />',
        '<meta name="robots" content="noindex, follow" />',
    )
    breadcrumb_items = [("Home", f"{BASE_URL}/")]
    if label:
        breadcrumb_items.append((label, f"{BASE_URL}/{deal.category}"))
    breadcrumb_items.append((deal.title[:60], url))
    seo_snippet = build_deal_product_jsonld(deal) + build_breadcrumb_jsonld(breadcrumb_items)
    head = inject_seo_block(head, seo_snippet)

    if deal.thumbnail_url:
        media_html = f'<img src="{esc(deal.thumbnail_url)}" alt="{esc(deal.title)}" style="width:100%;max-width:320px;border-radius:10px;border:1px solid var(--border)" />'
    else:
        media_html = '<div class="deal-card-icon-fallback" style="width:320px;max-width:100%;height:220px"></div>'

    price = format_price(deal.deal_price, deal.currency)
    original = format_price(deal.original_price, deal.currency)
    price_html = (
        f'<span class="price-current" style="font-size:22px">{esc(price)}</span>' if price else ""
    )
    if original:
        price_html += f'<span class="price-original">{esc(original)}</span>'
    discount_html = (
        f'<span class="discount-badge">{round(deal.discount_pct)}% off</span>' if deal.discount_pct else ""
    )

    breadcrumb_nav = ' <span aria-hidden="true">›</span> '.join(
        (f'<a href="{path}">{esc(name)}</a>' if path != url else esc(name))
        for name, path in [("Home", "/")] + ([(label, f"/{deal.category}/")] if label else []) + [(deal.title[:60], url)]
    )

    target = deal.affiliate_url or deal.url
    see_more_href = f"/{deal.category}/" if label else "/"
    see_more_label = f"See more {label} deals" if label else "See more deals"

    body = f"""  <body>
    <!-- Google Tag Manager (noscript) -->
    <noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-T7MD3LW5"
    height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
    <!-- End Google Tag Manager -->
{DISCLOSURE_AND_CONSENT_HTML}
    <div style="max-width:900px;margin:0 auto;padding:24px 16px 60px">
      <nav aria-label="Breadcrumb" style="font-size:12px;color:var(--muted);margin-bottom:20px">
        {breadcrumb_nav}
      </nav>
      <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start">
        {media_html}
        <div style="flex:1;min-width:260px">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:10px">
            <span class="cat-chip">{esc(deal.category)}</span>
            {discount_html}
          </div>
          <h1 style="font-size:22px;line-height:1.3;margin:0 0 12px">{esc(deal.title)}</h1>
          <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px">{price_html}</div>
          <p style="color:var(--muted);font-size:13px;margin:0 0 18px">Sold by {esc(deal.merchant or deal.source)} · Posted {esc(format_date(deal.posted_at))}</p>
          <a href="{esc(target)}" target="_blank" rel="{outbound_rel(deal)}"
             style="display:inline-block;background:var(--accent);color:#0a0c12;font-weight:700;font-size:14px;padding:12px 26px;border-radius:999px;text-decoration:none">
            Get This Deal →
          </a>
          <p style="font-size:11px;color:var(--muted);margin-top:12px;max-width:420px">
            Price and availability last confirmed {esc(format_date(deal.posted_at))}; subject to change on the retailer's site.
            This is an affiliate link — Hack the Deal may earn a commission at no extra cost to you.
          </p>
        </div>
      </div>
      <p style="margin-top:36px;font-size:13px"><a href="{esc(see_more_href)}">← {esc(see_more_label)}</a></p>
    </div>
{render_static_footer()}
  </body>
</html>
"""
    return head + body


# ── Sitemap ──────────────────────────────────────────────────────────────

STATIC_PAGES = [
    ("/", date.today().isoformat(), "daily", "1.0"),
    ("/about.html", "2026-07-27", "monthly", "0.5"),
    ("/contact.html", "2026-07-21", "monthly", "0.4"),
    ("/privacy.html", "2026-07-21", "monthly", "0.3"),
    ("/terms.html", "2026-07-22", "monthly", "0.3"),
]


def build_sitemap(all_deals: list[Deal]) -> str:
    # Deal permalinks are deliberately left out — they're noindex (see
    # build_deal_page) precisely because they're too thin to be worth a
    # search engine's attention individually, so listing 500+ of them here
    # would be asking Google to evaluate the same thing twice, just in two
    # different places. `all_deals` is still a param so callers don't need
    # to change — kept for the deal-count log line in main(), not used here.
    urls = list(STATIC_PAGES)
    today = date.today().isoformat()
    for slug in CATEGORIES:
        urls.append((f"/{slug}/", today, "daily", "0.8"))

    entries = "\n".join(
        f"  <url>\n    <loc>{BASE_URL}{loc}</loc>\n    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{freq}</changefreq>\n    <priority>{priority}</priority>\n  </url>"
        for loc, lastmod, freq, priority in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entries}\n</urlset>\n'


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    head_template = re.search(r"<!doctype html>.*?</head>", template, re.DOTALL | re.IGNORECASE).group(0) + "\n"

    with SessionLocal() as session:
        for slug, copy in CATEGORIES.items():
            deals = [] if slug in NO_PRERENDER_CATEGORIES else fetch_category_deals(session, slug)
            page = build_page(template, slug, copy["h1"], copy["description"], copy.get("guide", ""), deals)

            dir_path = ROOT / "frontend" / slug
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / "index.html").write_text(page, encoding="utf-8")
            print(f"wrote {(dir_path / 'index.html').relative_to(ROOT)} ({len(deals)} deals)")

        # Homepage.
        home_deals = fetch_home_deals(session)
        home_page = build_page(template, "", HOME_COPY["h1"], HOME_COPY["description"], HOME_COPY["guide"], home_deals)
        TEMPLATE_PATH.write_text(home_page, encoding="utf-8")
        print(f"wrote {TEMPLATE_PATH.relative_to(ROOT)} ({len(home_deals)} deals)")

        # Deal permalink pages — wipe and regenerate so aged-out deals'
        # pages disappear instead of lingering as stale thin content.
        all_deals = fetch_all_active_deals(session)
        deal_dir = ROOT / "frontend" / "deal"
        if deal_dir.exists():
            shutil.rmtree(deal_dir)
        deal_dir.mkdir(parents=True)
        for deal in all_deals:
            page_dir = deal_dir / f"{deal.id}-{slugify(deal.title)}"
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "index.html").write_text(build_deal_page(head_template, deal), encoding="utf-8")
        print(f"wrote {len(all_deals)} deal permalink pages under {deal_dir.relative_to(ROOT)}")

    sitemap_path = ROOT / "frontend" / "sitemap.xml"
    sitemap_path.write_text(build_sitemap(all_deals), encoding="utf-8")
    print(
        f"wrote {sitemap_path.relative_to(ROOT)} "
        f"({len(CATEGORIES) + len(STATIC_PAGES)} urls — {len(all_deals)} deal permalinks intentionally excluded, see build_sitemap)"
    )


if __name__ == "__main__":
    main()
