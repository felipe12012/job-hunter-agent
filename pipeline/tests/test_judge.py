import json

from judge import is_strong_match
from models import JobListing


def make_listing() -> JobListing:
    return JobListing(
        id="acme-python-dev",
        title="Python Developer",
        company="Acme",
        url="https://www.getonbrd.com/jobs/programming/acme-python-dev",
        description="Build APIs with Python and Django.",
        source="getonbrd",
    )


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def make_payload(noul_value: float) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {"is_strong_match": {"type": "noul", "noul": noul_value}},
        "usage": {"input_tokens": 100, "output_tokens": 5},
    }


def test_is_strong_match_returns_true_for_high_noul(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(make_payload(0.92))

    monkeypatch.setattr("judge.requests.post", fake_post)

    result = is_strong_match(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is True


def test_is_strong_match_returns_false_for_low_noul(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(make_payload(0.1))

    monkeypatch.setattr("judge.requests.post", fake_post)

    result = is_strong_match(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is False


def test_is_strong_match_returns_none_on_missing_answer_key(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse({"model": "jev-1.13.0", "answers": {}, "usage": {}})

    monkeypatch.setattr("judge.requests.post", fake_post)

    result = is_strong_match(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None


def test_is_strong_match_returns_none_on_request_exception(monkeypatch):
    import requests as real_requests

    def fake_post(url, headers, json, timeout):
        raise real_requests.RequestException("boom")

    monkeypatch.setattr("judge.requests.post", fake_post)

    result = is_strong_match(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None


def test_is_strong_match_returns_none_on_non_numeric_noul(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            {"model": "jev-1.13.0", "answers": {"is_strong_match": {"type": "noul", "noul": None}}}
        )

    monkeypatch.setattr("judge.requests.post", fake_post)

    result = is_strong_match(make_listing(), cv={"stack": ["Python"]}, api_key="fake-key")

    assert result is None
