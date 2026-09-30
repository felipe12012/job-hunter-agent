import json

import pytest
import requests

import backfill_once


class FakeResponse:
    def __init__(self, status_code: int = 201):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"http error {self.status_code}")


def test_classify_source_detects_computrabajo_hex_ids():
    assert backfill_once.classify_source("F5F3BD9C17F43B3A61373E686DCF3405") == "computrabajo"


def test_classify_source_defaults_to_getonbrd():
    assert backfill_once.classify_source("principal-engineer-cocoon-remote") == "getonbrd"


def test_build_placeholder_row_shapes_computrabajo_url():
    row = backfill_once.build_placeholder_row("F5F3BD9C17F43B3A61373E686DCF3405", user_id="u-1")

    assert row["source"] == "computrabajo"
    assert row["url"] == "https://cl.computrabajo.com/backfill/F5F3BD9C17F43B3A61373E686DCF3405"
    assert row["judge_result"] is False
    assert row["user_id"] == "u-1"


def test_build_placeholder_row_shapes_getonbrd_url():
    row = backfill_once.build_placeholder_row("principal-engineer-cocoon-remote", user_id="u-1")

    assert row["source"] == "getonbrd"
    assert row["url"] == "https://www.getonbrd.com/jobs/programming/principal-engineer-cocoon-remote"


def test_run_sends_ignore_duplicates_header_for_idempotent_reruns(monkeypatch, tmp_path):
    # Review Focus: re-running this script by accident must not crash on
    # ids already inserted by a previous run.
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text(
        json.dumps(["acme-python-dev", "F5F3BD9C17F43B3A61373E686DCF3405"]), encoding="utf-8"
    )
    monkeypatch.setattr(backfill_once, "SEEN_JOBS_PATH", seen_path)

    sent = {}

    def fake_post(url, headers, json, timeout):
        sent["headers"] = headers
        sent["json"] = json
        return FakeResponse(status_code=201)

    monkeypatch.setattr("backfill_once.requests.post", fake_post)

    backfill_once.run(supabase_url="https://x.supabase.co", service_role_key="fake-key", user_id="u-1")

    assert sent["headers"]["Prefer"] == "resolution=ignore-duplicates"
    assert len(sent["json"]) == 2
    assert {row["source"] for row in sent["json"]} == {"getonbrd", "computrabajo"}


def test_run_raises_on_request_exception(monkeypatch, tmp_path):
    seen_path = tmp_path / "seen_jobs.json"
    seen_path.write_text(json.dumps(["acme-python-dev"]), encoding="utf-8")
    monkeypatch.setattr(backfill_once, "SEEN_JOBS_PATH", seen_path)

    def fake_post(url, headers, json, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr("backfill_once.requests.post", fake_post)

    with pytest.raises(requests.RequestException):
        backfill_once.run(supabase_url="https://x.supabase.co", service_role_key="fake-key", user_id="u-1")
