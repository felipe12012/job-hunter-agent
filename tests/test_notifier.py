from models import JobListing, ScoredListing
from notifier import send_digest


def make_scored(job_id: str, match_pct: int) -> ScoredListing:
    listing = JobListing(
        id=job_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{job_id}",
        description="Build APIs with Python.",
    )
    return ScoredListing(
        listing=listing,
        match_pct=match_pct,
        reasoning="Good fit.",
        draft_message="Hi, I'm interested...",
    )


class FakeResponse:
    def raise_for_status(self):
        return None


def test_send_digest_sends_when_qualifying_matches_exist(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["url"] = url
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    scored = [make_scored("acme-python-dev", 90), make_scored("beta-dev", 60)]
    result = send_digest(scored, bot_token="fake-token", chat_id="12345")

    assert result is True
    assert sent["json"]["chat_id"] == "12345"
    assert "Python Developer" in sent["json"]["text"]
    assert "fake-token" in sent["url"]


def test_send_digest_skips_send_when_no_qualifying_matches(monkeypatch):
    called = {"count": 0}

    def fake_post(url, json, timeout):
        called["count"] += 1
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    scored = [make_scored("beta-dev", 60)]
    result = send_digest(scored, bot_token="fake-token", chat_id="12345")

    assert result is False
    assert called["count"] == 0


def test_send_digest_caps_at_three_listings(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    scored = [make_scored(f"job-{i}", 80 + i) for i in range(5)]
    send_digest(scored, bot_token="fake-token", chat_id="12345")

    assert sent["json"]["text"].count("% match") == 3


def test_send_digest_sends_plain_text_with_markdown_special_chars(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    listing = JobListing(
        id="weird-job",
        title="Senior *Python* Dev [Remote]",
        company="Under_score & `Ticks` Inc",
        url="https://www.getonbrd.com/jobs/programming/weird-job",
        description="n/a",
    )
    scored = [
        ScoredListing(
            listing=listing,
            match_pct=95,
            reasoning="Great fit_with *unbalanced* markdown [brackets and `backticks`",
            draft_message="Hi, I'm *very* interested_in this [role] and use `Python` daily",
        )
    ]

    result = send_digest(scored, bot_token="fake-token", chat_id="12345")

    assert result is True
    assert "parse_mode" not in sent["json"]
    assert "Senior *Python* Dev [Remote]" in sent["json"]["text"]


def test_send_digest_truncates_long_text(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    long_reasoning = "x" * 5000
    listing = JobListing(
        id="verbose-job",
        title="Python Developer",
        company="Acme",
        url="https://www.getonbrd.com/jobs/programming/verbose-job",
        description="n/a",
    )
    scored = [
        ScoredListing(
            listing=listing,
            match_pct=95,
            reasoning=long_reasoning,
            draft_message="hi",
        )
    ]

    result = send_digest(scored, bot_token="fake-token", chat_id="12345")

    assert result is True
    assert len(sent["json"]["text"]) <= 4000


def test_send_digest_raises_on_telegram_error(monkeypatch):
    import requests as real_requests

    def fake_post(url, json, timeout):
        raise real_requests.RequestException("telegram down")

    monkeypatch.setattr("notifier.requests.post", fake_post)

    scored = [make_scored("acme-python-dev", 90)]

    try:
        send_digest(scored, bot_token="fake-token", chat_id="12345")
        assert False, "expected RequestException to propagate"
    except real_requests.RequestException:
        pass
