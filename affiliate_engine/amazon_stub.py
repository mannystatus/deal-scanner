"""
Placeholder — Amazon links are already tagged directly in worker.py
(_retag_amazon_url / _AMAZON_TAG) before this module is ever consulted, so
this stub is never actually called in the current pipeline. Left here so
link_builder.py has one consistent entry point for every merchant, matching
the shape of the other three networks, in case Amazon tagging ever needs to
move into this registry instead.
"""


def build_amazon_link(destination_url: str, sub_id: str = "") -> str:
    raise NotImplementedError(
        "Amazon links are tagged in worker.py, not through this stub."
    )
