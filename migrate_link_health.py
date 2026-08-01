#!/usr/bin/env python3
"""
One-time schema migration: add deals.is_dead and deals.link_checked_at.

No backfill needed — every existing deal starts as is_dead=False with
link_checked_at=NULL, which is correct: link_health.py's recheck rotation
picks up never-checked deals first (see _active_deals_query), so every
existing deal gets its first real liveness check within the normal
once-per-week rotation instead of needing a bulk pass here.

Usage: python3 migrate_link_health.py
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
            if "is_dead" not in cols:
                conn.execute(text("ALTER TABLE deals ADD COLUMN is_dead BOOLEAN DEFAULT 0"))
                logger.info("Added is_dead column (SQLite).")
            else:
                logger.info("is_dead column already present.")
            if "link_checked_at" not in cols:
                conn.execute(text("ALTER TABLE deals ADD COLUMN link_checked_at TIMESTAMP"))
                logger.info("Added link_checked_at column (SQLite).")
            else:
                logger.info("link_checked_at column already present.")
            conn.commit()
        else:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS is_dead BOOLEAN NOT NULL DEFAULT false"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS link_checked_at TIMESTAMPTZ"))
            conn.commit()
            logger.info("Ensured is_dead and link_checked_at columns exist (PostgreSQL).")


if __name__ == "__main__":
    main()
