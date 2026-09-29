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
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)

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


def test_fetch_listings_combines_results_from_all_sources(monkeypatch):
    monkeypatch.setattr(
        main, "fetch_getonbrd_listings", lambda keywords: [make_listing("getonbrd-job")]
    )
    monkeypatch.setattr(
        main, "fetch_computrabajo_listings", lambda keywords: [make_listing("computrabajo-job")]
    )

    listings = main.fetch_listings(["Python"])

    ids = {listing.id for listing in listings}
    assert ids == {"getonbrd-job", "computrabajo-job"}


def test_fetch_listings_continues_when_only_one_source_fails(monkeypatch):
    def failing_fetch(keywords):
        raise RuntimeError("getonbrd is down")

    monkeypatch.setattr(main, "fetch_getonbrd_listings", failing_fetch)
    monkeypatch.setattr(
        main, "fetch_computrabajo_listings", lambda keywords: [make_listing("computrabajo-job")]
    )

    listings = main.fetch_listings(["Python"])

    assert [listing.id for listing in listings] == ["computrabajo-job"]


def test_fetch_listings_raises_only_when_all_sources_fail(monkeypatch):
    def failing_fetch(keywords):
        raise RuntimeError("source is down")

    monkeypatch.setattr(main, "fetch_getonbrd_listings", failing_fetch)
    monkeypatch.setattr(main, "fetch_computrabajo_listings", failing_fetch)

    try:
        main.fetch_listings(["Python"])
        assert False, "expected RuntimeError when every source fails"
    except RuntimeError:
        pass


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


def test_run_marks_seen_without_calling_deepseek_when_judge_rejects(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: False)

    def unexpected_score_listing(listing, cv):
        raise AssertionError("score_listing should never be called when the judge rejects a listing")

    monkeypatch.setattr(main, "score_listing", unexpected_score_listing)

    sent = {}

    def fake_send_digest(scored, match_threshold):
        sent["scored"] = scored
        return False

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert sent["scored"] == []
    saved = json.loads(seen_path.read_text(encoding="utf-8"))
    assert saved == ["acme-python-dev"]


def test_run_skips_and_retries_listing_when_judge_fails(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )

    def fake_is_strong_match(listing, cv):
        if listing.id == "acme-python-dev":
            return True
        return None

    monkeypatch.setattr(main, "is_strong_match", fake_is_strong_match)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setattr(main, "send_digest", lambda scored, match_threshold: True)

    exit_code = main.run()

    assert exit_code == 0
    saved = json.loads(seen_path.read_text(encoding="utf-8"))
    assert saved == ["acme-python-dev"]


def test_run_returns_nonzero_when_all_listings_fail_judge(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "SEEN_JOBS_PATH", seen_path)
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: None)

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
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
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
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
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
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
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
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
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
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
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
