import pytest
import requests

from db import filter_unseen, insert_listing, load_seen_keys, mark_notified
from models import JobListing


def make_listing(source: str = "getonbrd", listing_id: str = "acme-python-dev") -> JobListing:
    return JobListing(
        id=listing_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{listing_id}",
        description="Build APIs with Python.",
        source=source,
    )


class FakeResponse:
    def __init__(self, payload=None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"http error {self.status_code}")

    def json(self):
        return self._payload


def test_load_seen_keys_returns_source_id_tuples(monkeypatch):
    def fake_get(url, headers, params, timeout):
        assert params == {"select": "source,id"}
        return FakeResponse(
            [{"source": "getonbrd", "id": "acme-python-dev"}, {"source": "computrabajo", "id": "CT-001"}]
        )

    monkeypatch.setattr("db.requests.get", fake_get)

    result = load_seen_keys(supabase_url="https://x.supabase.co", service_role_key="fake-key")

    assert result == {("getonbrd", "acme-python-dev"), ("computrabajo", "CT-001")}


def test_load_seen_keys_raises_on_request_exception(monkeypatch):
    def fake_get(url, headers, params, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr("db.requests.get", fake_get)

    with pytest.raises(requests.RequestException):
        load_seen_keys(supabase_url="https://x.supabase.co", service_role_key="fake-key")


def test_filter_unseen_drops_known_source_id_pairs():
    listings = [make_listing(listing_id="acme-python-dev"), make_listing(listing_id="beta-dev")]
    seen = {("getonbrd", "acme-python-dev")}

    result = filter_unseen(listings, seen)

    assert [listing.id for listing in result] == ["beta-dev"]


def test_filter_unseen_keeps_same_id_from_a_different_source():
    listings = [make_listing(source="computrabajo", listing_id="acme-python-dev")]
    seen = {("getonbrd", "acme-python-dev")}

    result = filter_unseen(listings, seen)

    assert len(result) == 1


def test_insert_listing_sends_judge_rejected_row(monkeypatch):
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent["json"] = json
        return FakeResponse(status_code=201)

    monkeypatch.setattr("db.requests.post", fake_post)

    insert_listing(
        make_listing(),
        judge_result=False,
        supabase_url="https://x.supabase.co",
        service_role_key="fake-key",
        user_id="u-1",
    )

    assert sent["json"]["judge_result"] is False
    assert sent["json"]["match_pct"] is None
    assert sent["json"]["source"] == "getonbrd"
    assert sent["json"]["user_id"] == "u-1"


def test_insert_listing_sends_full_scored_row(monkeypatch):
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent["json"] = json
        return FakeResponse(status_code=201)

    monkeypatch.setattr("db.requests.post", fake_post)

    insert_listing(
        make_listing(),
        judge_result=True,
        match_pct=88,
        reasoning="Strong fit.",
        draft_message="Hi there...",
        supabase_url="https://x.supabase.co",
        service_role_key="fake-key",
    )

    assert sent["json"]["match_pct"] == 88
    assert sent["json"]["reasoning"] == "Strong fit."


def test_insert_listing_raises_on_request_exception(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr("db.requests.post", fake_post)

    with pytest.raises(requests.RequestException):
        insert_listing(
            make_listing(), judge_result=False, supabase_url="https://x.supabase.co", service_role_key="fake-key"
        )


def test_insert_listing_raises_on_duplicate_key_http_status(monkeypatch):
    # Review Focus: a scraper accidentally returning the same (source, id)
    # twice in one run must not crash the whole pipeline - it should surface
    # as a normal per-listing failure (HTTP 409 from Postgres' primary key
    # constraint), caught by main.py's existing per-listing try/except.
    def fake_post(url, headers, json, timeout):
        return FakeResponse(status_code=409)

    monkeypatch.setattr("db.requests.post", fake_post)

    with pytest.raises(requests.HTTPError):
        insert_listing(
            make_listing(), judge_result=False, supabase_url="https://x.supabase.co", service_role_key="fake-key"
        )


def test_mark_notified_patches_each_key(monkeypatch):
    calls = []

    def fake_patch(url, headers, params, json, timeout):
        calls.append(params)
        return FakeResponse(status_code=204)

    monkeypatch.setattr("db.requests.patch", fake_patch)

    mark_notified(
        [("getonbrd", "acme-python-dev"), ("computrabajo", "CT-001")],
        supabase_url="https://x.supabase.co",
        service_role_key="fake-key",
    )

    assert len(calls) == 2
    assert calls[0] == {"source": "eq.getonbrd", "id": "eq.acme-python-dev"}
    assert calls[1] == {"source": "eq.computrabajo", "id": "eq.CT-001"}


def test_mark_notified_raises_on_request_exception(monkeypatch):
    def fake_patch(url, headers, params, json, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr("db.requests.patch", fake_patch)

    with pytest.raises(requests.RequestException):
        mark_notified(
            [("getonbrd", "acme-python-dev")], supabase_url="https://x.supabase.co", service_role_key="fake-key"
        )
