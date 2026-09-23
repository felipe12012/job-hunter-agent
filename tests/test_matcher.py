import json

import requests

from matcher import score_listing
from models import JobListing


def make_listing() -> JobListing:
    return JobListing(
        id="acme-python-dev",
        title="Python Developer",
        company="Acme",
        url="https://www.getonbrd.com/jobs/programming/acme-python-dev",
        description="Build APIs with Python and Django.",
    )


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("http error")

    def json(self):
        return self._payload


def test_score_listing_parses_valid_response(monkeypatch):
    fake_content = json.dumps(
        {"match_pct": 88, "reasoning": "Strong Python/Django match.", "draft_message": "Hi there..."}
    )

    def fake_post(url, headers, json, timeout):
        return FakeResponse({"choices": [{"message": {"content": fake_content}}]})

    monkeypatch.setattr("matcher.requests.post", fake_post)

    result = score_listing(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is not None
    assert result.match_pct == 88
    assert result.reasoning == "Strong Python/Django match."
    assert result.listing.id == "acme-python-dev"


def test_score_listing_returns_none_on_malformed_json(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse({"choices": [{"message": {"content": "not json"}}]})

    monkeypatch.setattr("matcher.requests.post", fake_post)

    result = score_listing(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None


def test_score_listing_returns_none_on_request_exception(monkeypatch):
    import requests as real_requests

    def fake_post(url, headers, json, timeout):
        raise real_requests.RequestException("boom")

    monkeypatch.setattr("matcher.requests.post", fake_post)

    result = score_listing(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None


def test_score_listing_returns_none_on_missing_keys(monkeypatch):
    fake_content = json.dumps({"match_pct": 88})  # missing reasoning/draft_message

    def fake_post(url, headers, json, timeout):
        return FakeResponse({"choices": [{"message": {"content": fake_content}}]})

    monkeypatch.setattr("matcher.requests.post", fake_post)

    result = score_listing(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None


def test_score_listing_returns_none_on_empty_choices(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse({"choices": []})  # empty choices list raises IndexError

    monkeypatch.setattr("matcher.requests.post", fake_post)

    result = score_listing(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None


def test_score_listing_returns_none_on_non_coercible_match_pct(monkeypatch):
    fake_content = json.dumps(
        {"match_pct": None, "reasoning": "Test", "draft_message": "Test"}  # null match_pct
    )

    def fake_post(url, headers, json, timeout):
        return FakeResponse({"choices": [{"message": {"content": fake_content}}]})

    monkeypatch.setattr("matcher.requests.post", fake_post)

    result = score_listing(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None
