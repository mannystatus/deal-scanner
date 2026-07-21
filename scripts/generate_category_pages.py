#!/usr/bin/env python3
"""
Generates a real static index.html for every category route (frontend/<slug>/index.html)
from the frontend/index.html template, swapping in per-category <title>/meta/canonical/OG
tags and a BreadcrumbList so crawlers see unique, correctly-canonicalized metadata for
/drones, /gaming, etc. without needing to execute JS first.

The React app itself is untouched — these are the exact same bundle, just served with a
different <head>. Once it mounts, categoryFromPath() reads location.pathname and takes
over identically to how client-side navigation already works.

Run manually after editing CATEGORY_COPY in frontend/index.html (this dict must be kept
in sync with it by hand — there's no shared data file the two load from).

Usage: python3 scripts/generate_category_pages.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "frontend" / "index.html"
BASE_URL = "https://www.hackthedeal.com"

# Keep in sync with CATEGORY_COPY in frontend/index.html.
CATEGORIES = {
    "computers": {
        "h1": "Best Computer & Laptop Deals Today",
        "description": "Live price drops on laptops, desktops, monitors, and PC components. Hack the Deal tracks computer deals from top retailers continuously.",
    },
    "gaming": {
        "h1": "Best Gaming Deals Today",
        "description": "Live price drops on gaming consoles, PC games, accessories, and peripherals. Hack the Deal tracks gaming deals from top retailers continuously.",
    },
    "apple": {
        "h1": "Best Apple & iPhone Deals Today",
        "description": "Live price drops on iPhone, iPad, Mac, AirPods, and Apple Watch. Hack the Deal tracks Apple deals from top retailers continuously.",
    },
    "cameras": {
        "h1": "Best Camera & Photography Deals Today",
        "description": "Live price drops on cameras, lenses, drones, and photography gear. Hack the Deal tracks camera deals from top retailers continuously.",
    },
    "software": {
        "h1": "Best Software Deals Today",
        "description": "Live price drops on software licenses, subscriptions, and digital tools. Hack the Deal tracks software deals from top retailers continuously.",
    },
    "trading_cards": {
        "h1": "Best Trading Card Deals Today",
        "description": "Live price drops on trading card boxes, packs, and singles across Pokémon, sports, and TCGs. Hack the Deal tracks trading card deals continuously.",
    },
    "fashion": {
        "h1": "Best Fashion & Clothing Deals Today",
        "description": "Live price drops on clothing, shoes, and accessories for men and women. Hack the Deal tracks fashion deals from top retailers continuously.",
    },
    "beauty": {
        "h1": "Best Beauty & Health Deals Today",
        "description": "Live price drops on makeup, skincare, haircare, and health essentials. Hack the Deal tracks beauty deals from top retailers continuously.",
    },
    "shoes": {
        "h1": "Best Shoe Deals Today",
        "description": "Live price drops on sneakers, boots, and shoes for men, women, and kids. Hack the Deal tracks shoe deals from top retailers continuously.",
    },
    "travel": {
        "h1": "Best Travel Deals Today",
        "description": "Live price drops on flights, hotels, cruises, and travel gear. Hack the Deal tracks travel deals from top retailers continuously.",
    },
    "drones": {
        "h1": "Best Drone & FPV Parts Deals Today",
        "description": "Live price drops on drones, FPV parts, batteries, motors, and accessories straight from vendors like Pyrodrone and RaceDayQuads. Hack the Deal tracks drone deals continuously.",
    },
    "3d_printing": {
        "h1": "Best 3D Printer Deals Today",
        "description": "Live price drops on 3D printers and supplies straight from vendors like Elegoo, Anycubic, and Sovol. Hack the Deal tracks 3D printing deals continuously.",
    },
    "filament": {
        "h1": "Best 3D Printer Filament Deals Today",
        "description": "Live price drops on PLA, PETG, ABS, and specialty filament straight from vendors like Bambu Lab, Overture, and Polymaker. Hack the Deal tracks filament deals continuously.",
    },
}


def build_page(template: str, slug: str, h1: str, description: str) -> str:
    url = f"{BASE_URL}/{slug}"
    title = f"{h1} – Live Price Drops | Hack the Deal"

    html = template
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1)
    html = re.sub(
        r'<meta name="description" content="[^"]*" />',
        f'<meta name="description" content="{description}" />',
        html, count=1,
    )
    html = re.sub(
        r'<link rel="canonical" href="[^"]*" />',
        f'<link rel="canonical" href="{url}" />',
        html, count=1,
    )
    html = re.sub(
        r'<meta property="og:url" content="[^"]*" />',
        f'<meta property="og:url" content="{url}" />',
        html, count=1,
    )
    html = re.sub(
        r'<meta property="og:title" content="[^"]*" />',
        f'<meta property="og:title" content="{title}" />',
        html, count=1,
    )
    html = re.sub(
        r'<meta property="og:description" content="[^"]*" />',
        f'<meta property="og:description" content="{description}" />',
        html, count=1,
    )
    html = re.sub(
        r'<meta name="twitter:title" content="[^"]*" />',
        f'<meta name="twitter:title" content="{title}" />',
        html, count=1,
    )
    html = re.sub(
        r'<meta name="twitter:description" content="[^"]*" />',
        f'<meta name="twitter:description" content="{description}" />',
        html, count=1,
    )

    breadcrumb = f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      "itemListElement": [
        {{ "@type": "ListItem", "position": 1, "name": "Home", "item": "{BASE_URL}/" }},
        {{ "@type": "ListItem", "position": 2, "name": "{h1}", "item": "{url}" }}
      ]
    }}
    </script>
"""
    html = html.replace("</head>", breadcrumb + "  </head>", 1)
    return html


def main() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    redirect_lines = []
    for slug, copy in CATEGORIES.items():
        page = build_page(template, slug, copy["h1"], copy["description"])

        # Primary: <slug>/index.html — verified empirically that Cloudflare
        # Pages' _redirects rewrite rules do NOT reliably take effect on this
        # project (a request to /drones kept falling through to the generic
        # index.html SPA fallback even on a fresh, successfully-deployed
        # build), so this relies instead on the same directory-index
        # resolution that already makes / -> /index.html work, which is a
        # more fundamental static-asset match than a custom rule file.
        dir_path = ROOT / "frontend" / slug
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / "index.html").write_text(page, encoding="utf-8")
        print(f"wrote {(dir_path / 'index.html').relative_to(ROOT)}")

        # Also keep the flat <slug>.html around — harmless, and a direct
        # /drones.html link (if one exists anywhere) still resolves.
        flat_path = ROOT / "frontend" / f"{slug}.html"
        flat_path.write_text(page, encoding="utf-8")
        print(f"wrote {flat_path.relative_to(ROOT)}")

        redirect_lines.append(f"/{slug}  /{slug}.html  200")

    redirects_path = ROOT / "frontend" / "_redirects"
    header = (
        "# Cloudflare Pages rewrite rules (see scripts/generate_category_pages.py).\n"
        "# Status 200 = serve this file's content while keeping the requested URL,\n"
        "# as opposed to a 301/302 which would change the browser's address bar.\n"
        "# NOTE: as of 2026-07-21 these rules did not appear to take effect in\n"
        "# production (see git history) — the <slug>/index.html files are the\n"
        "# fix that's actually relied on. Left in place in case it starts\n"
        "# working after a future platform change; harmless either way.\n"
    )
    redirects_path.write_text(header + "\n".join(redirect_lines) + "\n", encoding="utf-8")
    print(f"wrote {redirects_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
