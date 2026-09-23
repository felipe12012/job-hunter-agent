import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from dedup import load_seen, filter_unseen, mark_seen
from matcher import load_cv, score_listing
from notifier import send_digest
from sources.getonbrd import fetch_listings

SEEN_JOBS_PATH = Path(__file__).parent / "data" / "seen_jobs.json"
CV_PATH = Path(__file__).parent / "cv.json"
DEFAULT_MATCH_THRESHOLD = 80

load_dotenv(Path(__file__).parent / ".env")


def run() -> int:
    cv = load_cv(str(CV_PATH))
    keywords = cv.get("stack", [])

    try:
        listings = fetch_listings(keywords)
    except Exception as exc:
        print(f"Scraper failed: {exc}", file=sys.stderr)
        return 1

    seen_ids = load_seen(SEEN_JOBS_PATH)
    unseen = filter_unseen(listings, seen_ids)

    scored = []
    for listing in unseen:
        result = score_listing(listing, cv)
        if result is None:
            print(f"Skipping {listing.id}: scoring failed, will retry next run", file=sys.stderr)
            continue
        scored.append(result)

    if unseen and not scored:
        print(
            "All listings failed to score; likely a broken API integration (bad/expired API key, "
            "no balance, or persistent errors). Aborting without sending a digest.",
            file=sys.stderr,
        )
        return 1

    raw_threshold = os.environ.get("MATCH_THRESHOLD")
    match_threshold = int(raw_threshold) if raw_threshold else DEFAULT_MATCH_THRESHOLD

    try:
        send_digest(scored, match_threshold=match_threshold)
    except Exception as exc:
        print(f"Notification failed: {exc}", file=sys.stderr)
        return 1

    processed_ids = [result.listing.id for result in scored]
    mark_seen(SEEN_JOBS_PATH, seen_ids, processed_ids)
    return 0


if __name__ == "__main__":
    sys.exit(run())
