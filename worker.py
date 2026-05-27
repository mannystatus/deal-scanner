import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from db import init_db, get_session, upsert_deal
from parsers import parse_title
from rss_source import iter_all_feeds

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    from urllib.parse import urlparse
    db_url = os.getenv("DATABASE_URL", "sqlite:///deals.db")
    parsed = urlparse(db_url)
    logger.info("Connecting to: %s://%s%s", parsed.scheme, parsed.hostname or "(local)", parsed.path)
    init_db()
    total_new = 0

    with get_session() as session:
        for post in iter_all_feeds():
            parsed = parse_title(post["title"], post["url"], post["source"])
            if upsert_deal(
                session,
                parsed,
                subreddit=post["source"],
                reddit_id=post["reddit_id"],
                posted_at=post["posted_at"],
            ):
                total_new += 1

    logger.info("Done. %d total new deals ingested.", total_new)
    return total_new


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
