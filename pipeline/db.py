import os

import requests

from models import JobListing

LISTINGS_PATH = "/rest/v1/listings"
PAGE_SIZE = 1000


def _base_url(supabase_url: str | None = None) -> str:
    return supabase_url or os.environ.get("SUPABASE_URL", "")


def _service_key(service_role_key: str | None = None) -> str:
    return service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _user_id(user_id: str | None = None) -> str:
    return user_id or os.environ.get("BACKFILL_USER_ID", "")


def _auth_headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def load_seen_keys(supabase_url: str | None = None, service_role_key: str | None = None) -> set[tuple[str, str]]:
    # PostgREST caps a single response at a fixed row count (default 1000),
    # returning HTTP 200 with a partial result rather than an error - page
    # through with offset/limit until a short page confirms we've reached the end.
    url = _base_url(supabase_url)
    key = _service_key(service_role_key)
    keys: set[tuple[str, str]] = set()
    offset = 0
    while True:
        response = requests.get(
            f"{url}{LISTINGS_PATH}",
            headers=_auth_headers(key),
            params={"select": "source,id", "offset": offset, "limit": PAGE_SIZE},
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json()
        keys.update((row["source"], row["id"]) for row in rows)
        if len(rows) < PAGE_SIZE:
            return keys
        offset += PAGE_SIZE


def filter_unseen(listings: list[JobListing], seen_keys: set[tuple[str, str]]) -> list[JobListing]:
    return [listing for listing in listings if (listing.source, listing.id) not in seen_keys]


def insert_listing(
    listing: JobListing,
    judge_result: bool,
    match_pct: int | None = None,
    reasoning: str | None = None,
    draft_message: str | None = None,
    supabase_url: str | None = None,
    service_role_key: str | None = None,
    user_id: str | None = None,
) -> None:
    url = _base_url(supabase_url)
    key = _service_key(service_role_key)
    headers = _auth_headers(key)
    headers["Content-Type"] = "application/json"

    response = requests.post(
        f"{url}{LISTINGS_PATH}",
        headers=headers,
        json={
            "source": listing.source,
            "id": listing.id,
            "title": listing.title,
            "company": listing.company,
            "url": listing.url,
            "description": listing.description,
            "judge_result": judge_result,
            "match_pct": match_pct,
            "reasoning": reasoning,
            "draft_message": draft_message,
            "user_id": _user_id(user_id),
        },
        timeout=30,
    )
    response.raise_for_status()


def mark_notified(
    keys: list[tuple[str, str]],
    supabase_url: str | None = None,
    service_role_key: str | None = None,
) -> None:
    url = _base_url(supabase_url)
    key = _service_key(service_role_key)
    headers = _auth_headers(key)
    headers["Content-Type"] = "application/json"

    for source, listing_id in keys:
        response = requests.patch(
            f"{url}{LISTINGS_PATH}",
            headers=headers,
            params={"source": f"eq.{source}", "id": f"eq.{listing_id}"},
            json={"notified": True},
            timeout=30,
        )
        response.raise_for_status()
