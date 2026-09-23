import json

import main
from models import JobListing, ScoredListing


def make_listing(job_id: str) -> JobListing:
    return JobListing(
        id=job_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{job_id}",
        description="Build APIs with Python.",
    )


def test_run_marks_only_successfully_scored_listings(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )

    def fake_score_listing(listing, cv):
        if listing.id == "acme-python-dev":
            return ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi")
        return None

    monkeypatch.setattr(main, "score_listing", fake_score_listing)
    monkeypatch.setattr(main, "send_digest", lambda scored, match_threshold: True)

    exit_code = main.run()

    assert exit_code == 0
    saved = json.loads(seen_path.read_text(encoding="utf-8"))
    assert saved == ["acme-python-dev"]


def test_run_returns_nonzero_when_scraper_fails(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})

    def failing_fetch(keywords):
        raise RuntimeError("site down")

    monkeypatch.setattr(main, "fetch_listings", failing_fetch)

    exit_code = main.run()

    assert exit_code == 1
    saved = json.loads(seen_path.read_text(encoding="utf-8"))
    assert saved == []


def test_run_returns_nonzero_when_all_listings_fail_to_score(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )
    monkeypatch.setattr(main, "score_listing", lambda listing, cv: None)

    exit_code = main.run()

    assert exit_code == 1
    saved = json.loads(seen_path.read_text(encoding="utf-8"))
    assert saved == []


def test_run_returns_nonzero_when_notification_fails(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )

    def failing_send(scored, match_threshold):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(main, "send_digest", failing_send)

    exit_code = main.run()

    assert exit_code == 1
    saved = json.loads(seen_path.read_text(encoding="utf-8"))
    assert saved == []


def test_run_uses_match_threshold_from_env(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=65, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setenv("MATCH_THRESHOLD", "60")

    received = {}

    def fake_send_digest(scored, match_threshold):
        received["match_threshold"] = match_threshold
        return True

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert received["match_threshold"] == 60


def test_run_defaults_match_threshold_when_env_is_empty_string(monkeypatch, tmp_path):
    # GitHub Actions passes an unset `vars.*` reference as an empty string,
    # not a missing key - the default must kick in for that case too.
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setenv("MATCH_THRESHOLD", "")

    received = {}

    def fake_send_digest(scored, match_threshold):
        received["match_threshold"] = match_threshold
        return True

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert received["match_threshold"] == 80


def test_run_defaults_match_threshold_when_env_unset(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.delenv("MATCH_THRESHOLD", raising=False)

    received = {}

    def fake_send_digest(scored, match_threshold):
        received["match_threshold"] = match_threshold
        return True

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert received["match_threshold"] == 80
