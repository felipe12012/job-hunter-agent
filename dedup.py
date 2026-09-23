import json
from pathlib import Path

from models import JobListing


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        return set(json.load(f))


def filter_unseen(listings: list[JobListing], seen_ids: set[str]) -> list[JobListing]:
    return [listing for listing in listings if listing.id not in seen_ids]


def mark_seen(path: Path, seen_ids: set[str], new_ids: list[str]) -> None:
    updated = seen_ids | set(new_ids)
    with path.open("w", encoding="utf-8") as f:
        json.dump(sorted(updated), f, indent=2)
