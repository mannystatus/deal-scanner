"""
Run: python -m affiliate_engine.demo

Shows current behavior (everything pending -> untagged passthrough) and
what it looks like once a merchant is approved and wired up.
"""

from .link_builder import build_affiliate_link
from .merchants import get_merchant, Status

print("--- Current state (all pending) ---")
for name, url in [
    ("Best Buy", "https://www.bestbuy.com/site/example-laptop/123.p"),
    ("Nordstrom", "https://www.nordstrom.com/s/example-jacket/456"),
    ("Micro Center", "https://www.microcenter.com/product/789/example-gpu"),
]:
    print(f"{name}: {build_affiliate_link(name, url)}")

print("\n--- Simulating Best Buy approval on Impact ---")
best_buy = get_merchant("Best Buy")
best_buy.status = Status.APPROVED
best_buy.program_id = "9876"  # example ProgramId you'd get from Impact's dashboard

import os
os.environ["IMPACT_ACCOUNT_SID"] = "IRExampleSID123"  # example — set for real via env var

# Re-import config values picked up at builder construction time in a real app;
# for this demo we rebuild the config object to reflect the env var change.
from . import config
config.IMPACT.account_sid = os.environ["IMPACT_ACCOUNT_SID"]

print(f"Best Buy: {build_affiliate_link('Best Buy', 'https://www.bestbuy.com/site/example-laptop/123.p', sub_id='deal_4821')}")
