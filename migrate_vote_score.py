#!/usr/bin/env python3
"""
One-time schema migration: add the deals.vote_score column.

No backfill needed — vote_score wasn't captured for deals ingested before
this column existed, so NULL is the correct (honest) value for all of
them, same as it'll be going forward for sources with no voting mechanism
(DealNews, 9to5toys, WooCommerce/Bambulab catalogs). See rss_source.py's
_thumb_score() and reddit_source.py's iter_posts() for where new deals
start getting a real value.

Usage: python3 migrate_vote_score.py
"""
import logging
import os

from sqlalchemy import create_engine, text

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///deals.db")


def main() -> None:
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    engine = create_engine(DATABASE_URL, connect_args=connect_args)

    with engine.connect() as conn:
        if DATABASE_URL.startswith("sqlite"):
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(deals)")).fetchall()]
            if "vote_score" not in cols:
                conn.execute(text("ALTER TABLE deals ADD COLUMN vote_score INTEGER"))
                conn.commit()
                logger.info("Added vote_score column (SQLite).")
            else:
                logger.info("vote_score column already present.")
        else:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS vote_score INTEGER"))
            conn.commit()
            logger.info("Ensured vote_score column exists (PostgreSQL).")


if __name__ == "__main__":
    main()
