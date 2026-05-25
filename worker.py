import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from db import init_db, get_session, upsert_deal
from parsers import parse_title
from reddit_source import iter_posts

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

SUBREDDITS = [
    s.strip()
    for s in os.getenv(
        "SUBREDDITS", "buildapcsales,GameDeals,AppleDeals,PS5Deals,SwitchDeals"
    ).split(",")
    if s.strip()
]
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "100"))


def main() -> int:
    init_db()
    total_new = 0

    for subreddit in SUBREDDITS:
        logger.info("Fetching r/%s (limit=%d)", subreddit, FETCH_LIMIT)
        new_count = 0
        with get_session() as session:
            for post in iter_posts(subreddit, limit=FETCH_LIMIT):
                parsed = parse_title(post["title"], post["url"], subreddit)
                if upsert_deal(
                    session,
                    parsed,
                    subreddit=subreddit,
                    reddit_id=post["reddit_id"],
                    posted_at=post["posted_at"],
                ):
                    new_count += 1
        logger.info("r/%s: %d new deals", subreddit, new_count)
        total_new += new_count

    logger.info("Done. %d total new deals ingested.", total_new)
    return total_new


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
