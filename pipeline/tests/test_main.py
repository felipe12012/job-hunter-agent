import main
from models import JobListing, ScoredListing


def make_listing(job_id: str, source: str = "getonbrd") -> JobListing:
    return JobListing(
        id=job_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{job_id}",
        description="Build APIs with Python.",
        source=source,
    )


def test_fetch_listings_combines_results_from_all_sources(monkeypatch):
    monkeypatch.setattr(main, "fetch_getonbrd_listings", lambda keywords: [make_listing("getonbrd-job")])
    monkeypatch.setattr(
        main,
        "fetch_computrabajo_listings",
        lambda keywords: [make_listing("computrabajo-job", source="computrabajo")],
    )

    listings = main.fetch_listings(["Python"])

    ids = {listing.id for listing in listings}
    assert ids == {"getonbrd-job", "computrabajo-job"}


def test_fetch_listings_continues_when_only_one_source_fails(monkeypatch):
    def failing_fetch(keywords):
        raise RuntimeError("getonbrd is down")

    monkeypatch.setattr(main, "fetch_getonbrd_listings", failing_fetch)
    monkeypatch.setattr(
        main,
        "fetch_computrabajo_listings",
        lambda keywords: [make_listing("computrabajo-job", source="computrabajo")],
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


def test_run_returns_nonzero_when_scraper_fails(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})

    def failing_fetch(keywords):
        raise RuntimeError("site down")

    monkeypatch.setattr(main, "fetch_listings", failing_fetch)

    assert main.run() == 1


def test_run_returns_nonzero_when_seen_keys_load_fails(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])

    def failing_load_seen_keys():
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(main, "load_seen_keys", failing_load_seen_keys)

    assert main.run() == 1


def test_run_persists_and_notifies_only_successfully_scored_listings(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)

    def fake_score_listing(listing, cv):
        if listing.id == "acme-python-dev":
            return ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi")
        return None

    monkeypatch.setattr(main, "score_listing", fake_score_listing)

    inserted = []
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: inserted.append(
            listing.id
        ),
    )
    monkeypatch.setattr(
        main,
        "send_digest",
        lambda scored, match_threshold: [(s.listing.source, s.listing.id) for s in scored],
    )
    notified = []
    monkeypatch.setattr(main, "mark_notified", lambda keys: notified.extend(keys))

    exit_code = main.run()

    assert exit_code == 0
    assert inserted == ["acme-python-dev"]
    assert notified == [("getonbrd", "acme-python-dev")]


def test_run_persists_rejected_listing_without_calling_deepseek(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: False)

    def unexpected_score_listing(listing, cv):
        raise AssertionError("score_listing should never be called when the judge rejects a listing")

    monkeypatch.setattr(main, "score_listing", unexpected_score_listing)

    inserted = []
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: inserted.append(
            (listing.id, judge_result)
        ),
    )

    sent = {}

    def fake_send_digest(scored, match_threshold):
        sent["scored"] = scored
        return []

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    def unexpected_mark_notified(keys):
        raise AssertionError("mark_notified should not be called when nothing was sent")

    monkeypatch.setattr(main, "mark_notified", unexpected_mark_notified)

    exit_code = main.run()

    assert exit_code == 0
    assert inserted == [("acme-python-dev", False)]
    assert sent["scored"] == []


def test_run_retries_listing_when_judge_fails(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())

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

    inserted = []
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: inserted.append(
            listing.id
        ),
    )
    monkeypatch.setattr(main, "send_digest", lambda scored, match_threshold: [])
    monkeypatch.setattr(main, "mark_notified", lambda keys: None)

    exit_code = main.run()

    assert exit_code == 0
    assert inserted == ["acme-python-dev"]


def test_run_returns_nonzero_when_all_listings_fail_judge(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: None)

    assert main.run() == 1


def test_run_returns_nonzero_when_all_listings_fail_to_score(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(
        main,
        "fetch_listings",
        lambda keywords: [make_listing("acme-python-dev"), make_listing("beta-dev")],
    )
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(main, "score_listing", lambda listing, cv: None)

    assert main.run() == 1


def test_run_excludes_listing_from_digest_when_insert_fails(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )

    def failing_insert(listing, judge_result, match_pct=None, reasoning=None, draft_message=None):
        raise RuntimeError("supabase write failed")

    monkeypatch.setattr(main, "insert_listing", failing_insert)

    def unexpected_send_digest(scored, match_threshold):
        raise AssertionError("send_digest should not be called when nothing was successfully processed")

    monkeypatch.setattr(main, "send_digest", unexpected_send_digest)

    assert main.run() == 1


def test_run_returns_nonzero_when_notification_fails(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: None,
    )

    def failing_send(scored, match_threshold):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(main, "send_digest", failing_send)

    assert main.run() == 1


def test_run_continues_when_mark_notified_fails(monkeypatch):
    # Review Focus: Telegram already received the digest by this point - a
    # failure recording that fact in Supabase must not turn into a nonzero
    # exit or an unhandled exception.
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: None,
    )
    monkeypatch.setattr(main, "send_digest", lambda scored, match_threshold: [("getonbrd", "acme-python-dev")])

    def failing_mark_notified(keys):
        raise RuntimeError("supabase patch failed")

    monkeypatch.setattr(main, "mark_notified", failing_mark_notified)

    assert main.run() == 0


def test_run_uses_match_threshold_from_env(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=65, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: None,
    )
    monkeypatch.setattr(main, "mark_notified", lambda keys: None)
    monkeypatch.setenv("MATCH_THRESHOLD", "60")

    received = {}

    def fake_send_digest(scored, match_threshold):
        received["match_threshold"] = match_threshold
        return []

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert received["match_threshold"] == 60


def test_run_defaults_match_threshold_when_env_is_empty_string(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: None,
    )
    monkeypatch.setattr(main, "mark_notified", lambda keys: None)
    monkeypatch.setenv("MATCH_THRESHOLD", "")

    received = {}

    def fake_send_digest(scored, match_threshold):
        received["match_threshold"] = match_threshold
        return []

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert received["match_threshold"] == 80


def test_run_defaults_match_threshold_when_env_unset(monkeypatch):
    monkeypatch.setattr(main, "load_cv", lambda path: {"stack": ["Python"]})
    monkeypatch.setattr(main, "fetch_listings", lambda keywords: [make_listing("acme-python-dev")])
    monkeypatch.setattr(main, "load_seen_keys", lambda: set())
    monkeypatch.setattr(main, "is_strong_match", lambda listing, cv: True)
    monkeypatch.setattr(
        main,
        "score_listing",
        lambda listing, cv: ScoredListing(listing=listing, match_pct=90, reasoning="ok", draft_message="hi"),
    )
    monkeypatch.setattr(
        main,
        "insert_listing",
        lambda listing, judge_result, match_pct=None, reasoning=None, draft_message=None: None,
    )
    monkeypatch.setattr(main, "mark_notified", lambda keys: None)
    monkeypatch.delenv("MATCH_THRESHOLD", raising=False)

    received = {}

    def fake_send_digest(scored, match_threshold):
        received["match_threshold"] = match_threshold
        return []

    monkeypatch.setattr(main, "send_digest", fake_send_digest)

    exit_code = main.run()

    assert exit_code == 0
    assert received["match_threshold"] == 80
