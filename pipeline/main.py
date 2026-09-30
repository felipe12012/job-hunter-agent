import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from dedup import load_seen, filter_unseen, mark_seen
from judge import is_strong_match
from matcher import load_cv, score_listing
from models import JobListing
from notifier import send_digest
from sources.computrabajo import fetch_listings as fetch_computrabajo_listings
from sources.getonbrd import fetch_listings as fetch_getonbrd_listings

SEEN_JOBS_PATH = Path(__file__).parent / "data" / "seen_jobs.json"
CV_PATH = Path(__file__).parent / "cv.json"
DEFAULT_MATCH_THRESHOLD = 80

load_dotenv(Path(__file__).parent / ".env")


def fetch_listings(keywords: list[str]) -> list[JobListing]:
    # Built fresh on every call (not hoisted to module scope) so that tests
    # can monkeypatch main.fetch_getonbrd_listings / main.fetch_computrabajo_listings
    # and have this function actually see the replacement.
    source_fetchers = [
        ("getonbrd", fetch_getonbrd_listings),
        ("computrabajo", fetch_computrabajo_listings),
    ]

    listings = []
    failures = 0
    for name, fetch in source_fetchers:
        try:
            listings.extend(fetch(keywords))
        except Exception as exc:
            failures += 1
            print(f"{name} scraper failed: {exc}", file=sys.stderr)

    if failures == len(source_fetchers):
        raise RuntimeError("All sources failed to fetch listings")

    return listings


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

    processed_ids = []
    scored = []
    for listing in unseen:
        judgement = is_strong_match(listing, cv)
        if judgement is None:
            print(f"Skipping {listing.id}: judge failed, will retry next run", file=sys.stderr)
            continue

        if not judgement:
            processed_ids.append(listing.id)
            continue

        result = score_listing(listing, cv)
        if result is None:
            print(f"Skipping {listing.id}: scoring failed, will retry next run", file=sys.stderr)
            continue

        processed_ids.append(listing.id)
        scored.append(result)

    if unseen and not processed_ids:
        print(
            "All listings failed to process; likely a broken API integration (bad/expired API key, "
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

    mark_seen(SEEN_JOBS_PATH, seen_ids, processed_ids)
    return 0


if __name__ == "__main__":
    sys.exit(run())
