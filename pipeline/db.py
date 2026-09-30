import os

import requests

from models import JobListing

LISTINGS_PATH = "/rest/v1/listings"


def _base_url(supabase_url: str | None = None) -> str:
    return supabase_url or os.environ.get("SUPABASE_URL", "")


def _service_key(service_role_key: str | None = None) -> str:
    return service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _auth_headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def load_seen_keys(supabase_url: str | None = None, service_role_key: str | None = None) -> set[tuple[str, str]]:
    url = _base_url(supabase_url)
    key = _service_key(service_role_key)
    response = requests.get(
        f"{url}{LISTINGS_PATH}",
        headers=_auth_headers(key),
        params={"select": "source,id"},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    return {(row["source"], row["id"]) for row in rows}


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
