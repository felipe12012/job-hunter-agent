# Supabase-backed state + read-only dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the git-committed `data/seen_jobs.json` dedup file with a real Supabase Postgres table (with real Auth + RLS), reorganize the repo into `pipeline/` (the cron) and `dashboard/` (a new read-only Next.js app on Vercel), and ship that dashboard.

**Architecture:** The existing pipeline (scrapers -> Jev -> DeepSeek -> Telegram) is unchanged in behavior; only its persistence layer moves from a flat file to Supabase (`db.py` replaces `dedup.py`, writing one row per processed listing). A new Next.js app under `dashboard/` reads those rows client-side via Supabase's anon key, gated by real Supabase Auth + a Postgres RLS policy.

**Tech Stack:** Python 3.12 (unchanged), Supabase (Postgres + Auth), Next.js (App Router) + `@supabase/ssr`, Vercel.

**Spec:** `docs/superpowers/specs/2026-09-29-supabase-dashboard-design.md`

## Global Constraints

- Repo splits into `pipeline/` (existing cron codebase, moved as-is) and `dashboard/` (new Next.js app) — one repo, `.github/workflows/daily.yml` uses `defaults.run.working-directory: pipeline`.
- `listings` table primary key is `(source, id)` — never a concatenated string key.
- `user_id` on `listings` is `not null` from day one, fixed to one real Supabase Auth user created as part of this work (single-user v1, schema ready for more later).
- The cron uses Supabase's **service_role key** (bypasses RLS, server-side only). The dashboard uses the **anon/publishable key** (safe to expose client-side) + a real logged-in session; RLS is what actually restricts rows to that user.
- `judge_result` is never null in a written row — a row is only ever written for a listing that reached a definitive Jev-or-DeepSeek outcome; anything that errored is simply not written (retried next run), matching today's dedup-on-existence semantics.
- Dashboard v1 is read-only: no mutations, no CV upload, no multi-user signup — explicitly out of scope.
- The backfill (Task 9) must complete before the new Supabase-backed `main.py` is allowed to process a real (scheduled or dispatched) run — otherwise the ~250 already-seen listings are silently forgotten and re-notified.

## Review Focus

- A scraper returning the same `(source, id)` twice in one run (e.g. a duplicate card on GetOnBoard) must not crash the whole pipeline run when the second `insert_listing` call hits the primary key — pinned in Task 6 with an HTTP-409-style test.
- `mark_notified` failing partway through (network blip after Telegram already received the digest) must not crash the run or re-raise past `main.py` — pinned in Task 8.
- The one-time backfill script must be safe to run twice (accidental re-run) without crashing on already-inserted ids — pinned in Task 9 via the `Prefer: resolution=ignore-duplicates` header.
- RLS must actually restrict `listings` rows to the owning user before the dashboard is treated as done — not unit-testable in Python; pinned in Task 2 (Supabase security advisors) and Task 10 (manual second-account check) as explicit non-pytest verification steps.
- Running the cutover out of order (new code live before the backfill completes) silently forgets ~250 already-seen listings — not a code bug to unit-test, but an ordering constraint made explicit in Task 9's step order and its own verification step (`load_seen_keys()` must return ~250 keys before any real run is allowed).

---

### Task 1: Reorganize the repo into `pipeline/` and `dashboard/`

**Files:**
- Move: `main.py`, `judge.py`, `matcher.py`, `notifier.py`, `models.py`, `parse_cv.py`, `dedup.py`, `sources/`, `requirements.txt`, `.env.example`, `cv.example.json`, `conftest.py`, `.gitignore`, `tests/`, `data/` -> all into `pipeline/`
- Modify: `.github/workflows/daily.yml`
- Modify: `pipeline/tests/test_workflow.py`

**Interfaces:**
- Produces: the directory layout every later task assumes (`pipeline/main.py`, `pipeline/tests/...`, etc.).

- [ ] **Step 1: Move the pipeline codebase into `pipeline/`**

```bash
mkdir -p pipeline
git mv main.py judge.py matcher.py notifier.py models.py parse_cv.py dedup.py pipeline/
git mv sources pipeline/sources
git mv requirements.txt .env.example cv.example.json conftest.py .gitignore pipeline/
git mv tests pipeline/tests
git mv data pipeline/data
```

If you have local untracked dev files (`.env`, `cv.json`, `cv.json.bak`) from earlier work, move those into `pipeline/` too by hand — `git mv` does not touch untracked files.

- [ ] **Step 2: Add `working-directory: pipeline` to the workflow**

`.github/workflows/daily.yml`:
```yaml
name: Daily Job Hunter

on:
  schedule:
    - cron: "0 8 * * *"
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    environment: env
    defaults:
      run:
        working-directory: pipeline
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Write cv.json from secret
        env:
          CV_JSON: ${{ secrets.CV_JSON }}
        run: echo "$CV_JSON" > cv.json

      - name: Run pipeline
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          JEV_API_KEY: ${{ secrets.JEV_API_KEY }}
          MATCH_THRESHOLD: ${{ vars.MATCH_THRESHOLD }}
        run: python main.py

      - name: Commit updated seen_jobs.json
        run: |
          git config user.name "job-hunter-agent"
          git config user.email "actions@users.noreply.github.com"
          git add data/seen_jobs.json
          git diff --cached --quiet || git commit -m "chore: update seen jobs"
          git push

      - name: Notify on failure
        if: failure()
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d text="⚠️ job-hunter-agent: el pipeline falló. Logs: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}"
```

(The "Commit updated seen_jobs.json" step and the `permissions` block are removed later in Task 9, once nothing needs them — leave them as-is for this task.)

- [ ] **Step 3: Update `pipeline/tests/test_workflow.py` for the new nesting depth and the new default**

`pipeline/tests/test_workflow.py`:
```python
from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "daily.yml"


def test_workflow_yaml_is_valid_and_scheduled_daily():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1 quirk).
    triggers = parsed[True]
    assert triggers["schedule"][0]["cron"] == "0 8 * * *"
    assert "workflow_dispatch" in triggers

    job = parsed["jobs"]["run-pipeline"]
    assert job["defaults"]["run"]["working-directory"] == "pipeline"
    assert job["environment"] == "env"
    assert parsed["permissions"]["contents"] == "write"


def test_workflow_uses_required_secrets():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for secret_name in ("DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CV_JSON", "JEV_API_KEY"):
        assert f"secrets.{secret_name}" in content


def test_workflow_passes_match_threshold_variable():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "vars.MATCH_THRESHOLD" in content


def test_workflow_notifies_telegram_on_failure():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    steps = parsed["jobs"]["run-pipeline"]["steps"]
    failure_steps = [step for step in steps if step.get("if") == "failure()"]

    assert len(failure_steps) == 1
    failure_step = failure_steps[0]
    assert "sendMessage" in failure_step["run"]
    assert "secrets.TELEGRAM_BOT_TOKEN" in content
    assert steps[-1] is failure_step
```

(Only the `WORKFLOW_PATH` line and the `assert job["defaults"]...` line actually changed from the pre-move version — the rest is unchanged, shown in full so there's no ambiguity about the file's final state.)

- [ ] **Step 3: Run the full suite from the new location**

Run: `cd pipeline && pytest -v`
Expected: PASS (54 tests — same count as before the move, nothing else changed)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: move pipeline into pipeline/, add dashboard/ working-directory to workflow"
```

---

### Task 2: Provision the Supabase project (schema, RLS, one real Auth user)

This task is infrastructure provisioning via the Supabase MCP tools, not application code — there is no pytest suite for it. Its "tests" are the verification calls in each step. Load the tools first if they are not already available: `ToolSearch("select:mcp__plugin_supabase_supabase__create_project,mcp__plugin_supabase_supabase__get_project,mcp__plugin_supabase_supabase__apply_migration,mcp__plugin_supabase_supabase__list_tables,mcp__plugin_supabase_supabase__get_project_url,mcp__plugin_supabase_supabase__get_publishable_keys,mcp__plugin_supabase_supabase__get_advisors")`.

**Interfaces:**
- Produces: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and `BACKFILL_USER_ID` (the Auth user's UUID) — every later task that talks to Supabase needs these four values. Record them somewhere the next task's implementer can read (the report file, per this skill's dispatch convention).

- [ ] **Step 1: Create the project**

Call `mcp__plugin_supabase_supabase__create_project` with `name: "job-hunter-agent"`, `organization_id: "twqzcuhfgnmovfusuwsw"` (the "draken Org" organization already confirmed in this conversation), `region: "us-east-1"`.

- [ ] **Step 2: Wait for it to become healthy**

Call `mcp__plugin_supabase_supabase__get_project` with the new project's id, repeating every ~10s.
Expected: `status` becomes `"ACTIVE_HEALTHY"`.

- [ ] **Step 3: Apply the schema migration**

Call `mcp__plugin_supabase_supabase__apply_migration` with `name: "create_listings_table"` and:
```sql
create table listings (
  source text not null,
  id text not null,
  title text not null,
  company text,
  url text not null,
  description text,
  judge_result boolean not null,
  match_pct integer,
  reasoning text,
  draft_message text,
  notified boolean not null default false,
  created_at timestamptz not null default now(),
  user_id uuid not null,
  primary key (source, id)
);

alter table listings enable row level security;

create policy "users read their own listings"
  on listings for select
  using (auth.uid() = user_id);
```

- [ ] **Step 4: Verify the table and RLS**

Call `mcp__plugin_supabase_supabase__list_tables`.
Expected: `listings` is present with `rls_enabled: true` (or equivalent field indicating RLS is on).

- [ ] **Step 5: Get the project URL and anon key**

Call `mcp__plugin_supabase_supabase__get_project_url` and `mcp__plugin_supabase_supabase__get_publishable_keys`.
Record both — this is `SUPABASE_URL` and `SUPABASE_ANON_KEY`.

- [ ] **Step 6: Get the service_role key**

The MCP tools deliberately do not expose this key (it bypasses RLS entirely). Ask the project owner to copy it from the Supabase Dashboard: **Settings -> API -> service_role secret** for this new project. Record it as `SUPABASE_SERVICE_ROLE_KEY`. Never print this value back verbatim in any report or log that isn't strictly necessary to hand to the next task.

- [ ] **Step 7: Create the one real Auth user**

```bash
curl -s -X POST "<SUPABASE_URL>/auth/v1/admin/users" \
  -H "apikey: <SUPABASE_SERVICE_ROLE_KEY>" \
  -H "Authorization: Bearer <SUPABASE_SERVICE_ROLE_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"email": "<project owner email>", "password": "<a real password, ask the project owner>", "email_confirm": true}'
```

Expected: HTTP 200 with a JSON body containing an `"id"` field (a UUID). Record it as `BACKFILL_USER_ID` — this becomes the fixed `user_id` used by every `insert_listing` call in Task 8 and the backfill in Task 9, and is the login for the dashboard in Task 10.

- [ ] **Step 8: Run the security advisor**

Call `mcp__plugin_supabase_supabase__get_advisors` with `type: "security"`.
Expected: no unaddressed issue naming the `listings` table (a clean result, or only issues about unrelated default project settings that don't apply here).

---

### Task 3: Add `source` to `JobListing`

**Files:**
- Modify: `pipeline/models.py`
- Modify: `pipeline/tests/test_models.py`, `pipeline/tests/test_matcher.py`, `pipeline/tests/test_judge.py`, `pipeline/tests/test_notifier.py`, `pipeline/tests/test_main.py`
- Delete: `pipeline/tests/test_dedup.py` (tests the module `dedup.py` that Task 9 removes; not worth updating twice)

**Interfaces:**
- Produces: `JobListing(id, title, company, url, description, source)` — every later task's test helpers that construct a `JobListing` must pass `source=...`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_models.py`:
```python
from models import JobListing, ScoredListing


def make_listing() -> JobListing:
    return JobListing(
        id="acme-python-dev",
        title="Python Developer",
        company="Acme",
        url="https://www.getonbrd.com/jobs/programming/acme-python-dev",
        description="Build backend services in Python.",
        source="getonbrd",
    )


def test_job_listing_fields():
    job = make_listing()
    assert job.id == "acme-python-dev"
    assert job.title == "Python Developer"
    assert job.company == "Acme"
    assert job.source == "getonbrd"


def test_scored_listing_wraps_listing():
    job = make_listing()
    scored = ScoredListing(
        listing=job,
        match_pct=85,
        reasoning="Strong Python match.",
        draft_message="Hi, I'd love to apply...",
    )
    assert scored.listing.id == "acme-python-dev"
    assert scored.match_pct == 85
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && pytest tests/test_models.py -v`
Expected: FAIL with `TypeError: JobListing.__init__() got an unexpected keyword argument 'source'`

- [ ] **Step 3: Add the field to `models.py`**

`pipeline/models.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class JobListing:
    id: str
    title: str
    company: str
    url: str
    description: str
    source: str


@dataclass(frozen=True)
class ScoredListing:
    listing: JobListing
    match_pct: int
    reasoning: str
    draft_message: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Fix every other test file's `JobListing(...)` construction**

Every other test file that builds a `JobListing` now fails the same way. Add `source="getonbrd"` to each (all of today's tests only exercise GetOnBoard-shaped fixtures; Task 5 adds the one Computrabajo-specific assertion separately):

`pipeline/tests/test_matcher.py` — in `make_listing()`, add `source="getonbrd"` alongside the other fields (same shape as Task 3's `test_models.py` change above).

`pipeline/tests/test_judge.py` — same: add `source="getonbrd"` to its `make_listing()`.

`pipeline/tests/test_notifier.py` — three separate `JobListing(...)` construction sites need `source="getonbrd"` added: the `listing = JobListing(...)` inside `make_scored()`, the `listing = JobListing(...)` inside `test_send_digest_sends_plain_text_with_markdown_special_chars`, and the `listing = JobListing(...)` inside `test_send_digest_truncates_long_text`.

`pipeline/tests/test_main.py` — add `source: str = "getonbrd"` as a parameter to its `make_listing(job_id: str)` helper, passing it through:
```python
def make_listing(job_id: str, source: str = "getonbrd") -> JobListing:
    return JobListing(
        id=job_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{job_id}",
        description="Build APIs with Python.",
        source=source,
    )
```

- [ ] **Step 6: Delete the dedup test file**

```bash
rm pipeline/tests/test_dedup.py
```

`dedup.py` itself is untouched and still works exactly as before — this only removes the test, because Task 9 deletes `dedup.py` and this test would need the same `source=` fix for zero benefit in the meantime.

- [ ] **Step 7: Run the full suite**

Run: `cd pipeline && pytest -v`
Expected: PASS, zero failures, zero errors (the exact count is one lower than Task 1's, since `test_dedup.py`'s 4 tests are gone and no new test functions were added in this task — only existing ones gained a `source=` keyword argument)

- [ ] **Step 8: Commit**

```bash
git add pipeline/models.py pipeline/tests/test_models.py pipeline/tests/test_matcher.py pipeline/tests/test_judge.py pipeline/tests/test_notifier.py pipeline/tests/test_main.py
git rm pipeline/tests/test_dedup.py
git commit -m "feat: add source field to JobListing"
```

---

### Task 4: Set `source="getonbrd"` in the GetOnBoard scraper

**Files:**
- Modify: `pipeline/sources/getonbrd.py`
- Modify: `pipeline/tests/test_getonbrd.py`

**Interfaces:**
- Consumes: `JobListing(..., source: str)` (Task 3).
- Produces: `parse_listings(...)` now returns `JobListing`s with `source == "getonbrd"` — Task 8's `main.py` relies on this being set correctly for every source.

- [ ] **Step 1: Write the failing assertion**

`pipeline/tests/test_getonbrd.py` — add one assertion line to the existing `test_parse_listings_filters_by_keyword` (the rest of that test, and the other three tests in the file, are unchanged):
```python
def test_parse_listings_filters_by_keyword():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    result = parse_listings(html, keywords=["python"])

    assert len(result) == 1
    listing = result[0]
    assert listing.id == "acme-python-dev"
    assert listing.title == "Python Developer"
    assert listing.company == "Acme"
    assert listing.source == "getonbrd"
    assert "Django" in listing.description
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && pytest tests/test_getonbrd.py::test_parse_listings_filters_by_keyword -v`
Expected: FAIL with `AttributeError` or a missing-`source`-keyword `TypeError` (whichever `JobListing(...)` in `getonbrd.py` throws first, since it isn't passing `source` yet)

- [ ] **Step 3: Add the field**

`pipeline/sources/getonbrd.py` — modify the `JobListing(...)` construction inside `parse_listings`:
```python
        listings.append(
            JobListing(
                id=job_id,
                title=title,
                company=company,
                url=url,
                description=summary,
                source="getonbrd",
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_getonbrd.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/sources/getonbrd.py pipeline/tests/test_getonbrd.py
git commit -m "feat: tag GetOnBoard listings with source=getonbrd"
```

---

### Task 5: Set `source="computrabajo"` in the Computrabajo scraper

**Files:**
- Modify: `pipeline/sources/computrabajo.py`
- Modify: `pipeline/tests/test_computrabajo.py`

**Interfaces:**
- Consumes: `JobListing(..., source: str)` (Task 3).
- Produces: `_build_listing(summary: dict, description: str) -> JobListing` (a new pure function, so the `source="computrabajo"` tag is directly unit-testable without a live network call, mirroring how `getonbrd.py`'s `parse_listings` is directly testable). `fetch_listings(...)` now returns `JobListing`s with `source == "computrabajo"`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_computrabajo.py` — add this test and the import it needs:
```python
from sources.computrabajo import _build_listing, parse_description, parse_listing_summaries
```
(replaces the existing `from sources.computrabajo import parse_description, parse_listing_summaries` import line)

```python
def test_build_listing_sets_computrabajo_source():
    summary = {
        "id": "CT-001",
        "title": "Desarrollador Python Django",
        "company": "Acme",
        "url": "https://cl.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-python-django-CT-001",
    }

    listing = _build_listing(summary, "Some real description")

    assert listing.source == "computrabajo"
    assert listing.id == "CT-001"
    assert listing.title == "Desarrollador Python Django"
    assert listing.description == "Some real description"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && pytest tests/test_computrabajo.py::test_build_listing_sets_computrabajo_source -v`
Expected: FAIL with `ImportError: cannot import name '_build_listing'`

- [ ] **Step 3: Extract `_build_listing` and set the source**

`pipeline/sources/computrabajo.py` — replace the tail of the file (the `fetch_listings` function) with:
```python
def _build_listing(summary: dict, description: str) -> JobListing:
    return JobListing(
        id=summary["id"],
        title=summary["title"],
        company=summary["company"],
        url=summary["url"],
        description=description,
        source="computrabajo",
    )


def fetch_listings(keywords: list[str]) -> list[JobListing]:
    summaries = parse_listing_summaries(fetch_html())

    lowered_keywords = [keyword.lower() for keyword in keywords]
    listings = []
    for summary in summaries:
        if not any(keyword in summary["title"].lower() for keyword in lowered_keywords):
            continue

        description = parse_description(fetch_html(summary["url"]))
        listings.append(_build_listing(summary, description))

    return listings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_computrabajo.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/sources/computrabajo.py pipeline/tests/test_computrabajo.py
git commit -m "feat: tag Computrabajo listings with source=computrabajo"
```

---

### Task 6: `db.py` — Supabase-backed dedup and result storage

**Files:**
- Create: `pipeline/db.py`
- Test: `pipeline/tests/test_db.py`

**Interfaces:**
- Consumes: `JobListing` (Task 3, now with `.source`).
- Produces: `load_seen_keys(supabase_url=None, service_role_key=None) -> set[tuple[str, str]]`, `filter_unseen(listings: list[JobListing], seen_keys: set[tuple[str, str]]) -> list[JobListing]`, `insert_listing(listing, judge_result, match_pct=None, reasoning=None, draft_message=None, supabase_url=None, service_role_key=None) -> None` (raises on failure), `mark_notified(keys: list[tuple[str, str]], supabase_url=None, service_role_key=None) -> None` (raises on failure) — all four consumed by `main.py` in Task 8.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_db.py`:
```python
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
    )

    assert sent["json"]["judge_result"] is False
    assert sent["json"]["match_pct"] is None
    assert sent["json"]["source"] == "getonbrd"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Write `db.py`**

`pipeline/db.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/db.py pipeline/tests/test_db.py
git commit -m "feat: add Supabase-backed db module (replaces dedup.py's role)"
```

---

### Task 7: `notifier.py` — return which listings were actually sent

**Files:**
- Modify: `pipeline/notifier.py`
- Modify: `pipeline/tests/test_notifier.py`

**Interfaces:**
- Consumes: `ScoredListing` (whose `.listing.source`/`.listing.id` now exist, from Task 3).
- Produces: `send_digest(...) -> list[tuple[str, str]]` (was `-> bool`) — `[]` means nothing sent. Consumed by `main.py` in Task 8.

- [ ] **Step 1: Update the tests for the new return type**

`pipeline/tests/test_notifier.py` — full file (the `JobListing(...)`/`make_scored` sites already have `source="getonbrd"` from Task 3; this step changes the return-value assertions and adds one new test):
```python
from models import JobListing, ScoredListing
from notifier import send_digest


def make_scored(job_id: str, match_pct: int) -> ScoredListing:
    listing = JobListing(
        id=job_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{job_id}",
        description="Build APIs with Python.",
        source="getonbrd",
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

    assert result == [("getonbrd", "acme-python-dev")]
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

    assert result == []
    assert called["count"] == 0


def test_send_digest_respects_custom_match_threshold(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    scored = [make_scored("beta-dev", 65)]
    result = send_digest(scored, bot_token="fake-token", chat_id="12345", match_threshold=60)

    assert result == [("getonbrd", "beta-dev")]
    assert "Python Developer" in sent["json"]["text"]


def test_send_digest_caps_at_three_listings(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr("notifier.requests.post", fake_post)

    scored = [make_scored(f"job-{i}", 80 + i) for i in range(5)]
    result = send_digest(scored, bot_token="fake-token", chat_id="12345")

    assert sent["json"]["text"].count("% match") == 3
    assert len(result) == 3


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
        source="getonbrd",
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

    assert result == [("getonbrd", "weird-job")]
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
        source="getonbrd",
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

    assert result == [("getonbrd", "verbose-job")]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && pytest tests/test_notifier.py -v`
Expected: FAIL — assertions like `result == [("getonbrd", "acme-python-dev")]` fail because `send_digest` still returns `True`

- [ ] **Step 3: Change `send_digest`'s return value**

`pipeline/notifier.py` — modify only the `send_digest` function (`format_digest` and the module constants are unchanged):
```python
def send_digest(
    scored_listings: list[ScoredListing],
    bot_token: str | None = None,
    chat_id: str | None = None,
    match_threshold: int = MATCH_THRESHOLD,
) -> list[tuple[str, str]]:
    qualifying = [s for s in scored_listings if s.match_pct >= match_threshold]
    if not qualifying:
        return []

    qualifying.sort(key=lambda s: s.match_pct, reverse=True)
    top = qualifying[:MAX_LISTINGS_PER_DIGEST]

    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    text = format_digest(top)
    if len(text) > MAX_TELEGRAM_TEXT_LENGTH:
        text = text[:MAX_TELEGRAM_TEXT_LENGTH]

    response = requests.post(
        TELEGRAM_URL_TEMPLATE.format(token=bot_token),
        json={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=30,
    )
    response.raise_for_status()
    return [(s.listing.source, s.listing.id) for s in top]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notifier.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/notifier.py pipeline/tests/test_notifier.py
git commit -m "feat: send_digest returns the (source, id) keys it actually sent"
```

---

### Task 8: Rewire `main.py` onto `db.py`

**Files:**
- Modify: `pipeline/main.py`
- Modify: `pipeline/tests/test_main.py`

**Interfaces:**
- Consumes: `load_seen_keys`, `filter_unseen`, `insert_listing`, `mark_notified` (Task 6); `send_digest -> list[tuple[str, str]]` (Task 7); `is_strong_match` (existing); `load_cv`, `score_listing` (existing); `fetch_getonbrd_listings`, `fetch_computrabajo_listings` (existing, now tagging `.source`).
- Produces: `run() -> int` (0/1), `fetch_listings(keywords) -> list[JobListing]` — both unchanged in name/shape from before, only their internals and what they call change.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_main.py` — full file:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && pytest tests/test_main.py -v`
Expected: FAIL — `main.py` still imports from `dedup`, has no `load_seen_keys`/`insert_listing`/`mark_notified` attributes to monkeypatch, and several will error with `AttributeError`

- [ ] **Step 3: Rewrite `main.py`**

`pipeline/main.py`:
```python
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from db import filter_unseen, insert_listing, load_seen_keys, mark_notified
from judge import is_strong_match
from matcher import load_cv, score_listing
from models import JobListing
from notifier import send_digest
from sources.computrabajo import fetch_listings as fetch_computrabajo_listings
from sources.getonbrd import fetch_listings as fetch_getonbrd_listings

CV_PATH = Path(__file__).parent / "cv.json"
DEFAULT_MATCH_THRESHOLD = 80

load_dotenv(Path(__file__).parent / ".env")


def fetch_listings(keywords: list[str]) -> list[JobListing]:
    # Built fresh on every call (not hoisted to module scope) so that tests
    # can monkeypatch main.fetch_getonbrd_listings / main.fetch_computrabajo_listings
    # and have this function actually see the replacement.
    source_fetchers = [
        ("getonbrd", fetch_getonbrd_listings),
        ("computrabajo", fetch_computrabajo_listings),
    ]

    listings = []
    failures = 0
    for name, fetch in source_fetchers:
        try:
            listings.extend(fetch(keywords))
        except Exception as exc:
            failures += 1
            print(f"{name} scraper failed: {exc}", file=sys.stderr)

    if failures == len(source_fetchers):
        raise RuntimeError("All sources failed to fetch listings")

    return listings


def run() -> int:
    cv = load_cv(str(CV_PATH))
    keywords = cv.get("stack", [])

    try:
        listings = fetch_listings(keywords)
    except Exception as exc:
        print(f"Scraper failed: {exc}", file=sys.stderr)
        return 1

    try:
        seen_keys = load_seen_keys()
    except Exception as exc:
        print(f"Could not load dedup state from Supabase: {exc}", file=sys.stderr)
        return 1

    unseen = filter_unseen(listings, seen_keys)

    processed_count = 0
    scored = []
    for listing in unseen:
        judgement = is_strong_match(listing, cv)
        if judgement is None:
            print(f"Skipping {listing.id}: judge failed, will retry next run", file=sys.stderr)
            continue

        if not judgement:
            try:
                insert_listing(listing, judge_result=False)
                processed_count += 1
            except Exception as exc:
                print(
                    f"Skipping {listing.id}: failed to persist judge result, will retry next run: {exc}",
                    file=sys.stderr,
                )
            continue

        result = score_listing(listing, cv)
        if result is None:
            print(f"Skipping {listing.id}: scoring failed, will retry next run", file=sys.stderr)
            continue

        try:
            insert_listing(
                listing,
                judge_result=True,
                match_pct=result.match_pct,
                reasoning=result.reasoning,
                draft_message=result.draft_message,
            )
            processed_count += 1
            scored.append(result)
        except Exception as exc:
            print(
                f"Skipping {listing.id}: failed to persist scored result, will retry next run: {exc}",
                file=sys.stderr,
            )

    if unseen and processed_count == 0:
        print(
            "All listings failed to process; likely a broken API integration (bad/expired API key, "
            "no balance, or persistent errors). Aborting without sending a digest.",
            file=sys.stderr,
        )
        return 1

    raw_threshold = os.environ.get("MATCH_THRESHOLD")
    match_threshold = int(raw_threshold) if raw_threshold else DEFAULT_MATCH_THRESHOLD

    try:
        sent_keys = send_digest(scored, match_threshold=match_threshold)
    except Exception as exc:
        print(f"Notification failed: {exc}", file=sys.stderr)
        return 1

    if sent_keys:
        try:
            mark_notified(sent_keys)
        except Exception as exc:
            print(f"Failed to mark listings as notified: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests across the whole `pipeline/` suite)

- [ ] **Step 6: Commit**

```bash
git add pipeline/main.py pipeline/tests/test_main.py
git commit -m "feat: rewire main.py onto db.py (Supabase) instead of dedup.py"
```

---

### Task 9: Backfill, cutover, and cleanup

**Files:**
- Create: `pipeline/backfill_once.py`
- Test: `pipeline/tests/test_backfill_once.py`
- Delete: `pipeline/dedup.py`, `pipeline/data/seen_jobs.json` (and `pipeline/data/` if now empty)
- Modify: `.github/workflows/daily.yml`
- Modify: `pipeline/tests/test_workflow.py`

**Interfaces:**
- Consumes: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `BACKFILL_USER_ID` (Task 2's output).
- Produces: nothing consumed by later tasks — this is the final pipeline-side integration point before the dashboard.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_backfill_once.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && pytest tests/test_backfill_once.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backfill_once'`

- [ ] **Step 3: Write `backfill_once.py`**

`pipeline/backfill_once.py`:
```python
import json
import os
import re
from pathlib import Path

import requests

SEEN_JOBS_PATH = Path(__file__).parent / "data" / "seen_jobs.json"
COMPUTRABAJO_ID_PATTERN = re.compile(r"^[0-9A-F]{32}$")


def classify_source(job_id: str) -> str:
    return "computrabajo" if COMPUTRABAJO_ID_PATTERN.match(job_id) else "getonbrd"


def build_placeholder_row(job_id: str, user_id: str) -> dict:
    source = classify_source(job_id)
    if source == "computrabajo":
        url = f"https://cl.computrabajo.com/backfill/{job_id}"
    else:
        url = f"https://www.getonbrd.com/jobs/programming/{job_id}"

    return {
        "source": source,
        "id": job_id,
        "title": "(backfill placeholder)",
        "company": None,
        "url": url,
        "description": None,
        "judge_result": False,
        "match_pct": None,
        "reasoning": None,
        "draft_message": None,
        "user_id": user_id,
    }


def run(supabase_url: str, service_role_key: str, user_id: str) -> None:
    seen_ids = json.loads(SEEN_JOBS_PATH.read_text(encoding="utf-8"))
    rows = [build_placeholder_row(job_id, user_id) for job_id in seen_ids]

    response = requests.post(
        f"{supabase_url}/rest/v1/listings",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates",
        },
        json=rows,
        timeout=60,
    )
    response.raise_for_status()
    print(f"Backfill request sent for {len(rows)} ids (duplicates silently ignored on re-run).")


if __name__ == "__main__":
    run(
        supabase_url=os.environ["SUPABASE_URL"],
        service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        user_id=os.environ["BACKFILL_USER_ID"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backfill_once.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit the script**

```bash
git add pipeline/backfill_once.py pipeline/tests/test_backfill_once.py
git commit -m "feat: add one-time backfill script for the Supabase cutover"
```

- [ ] **Step 6: Run the backfill for real — do this before anything in Step 7 or later**

```bash
cd pipeline
SUPABASE_URL="<from Task 2>" SUPABASE_SERVICE_ROLE_KEY="<from Task 2>" BACKFILL_USER_ID="<from Task 2>" python backfill_once.py
```
Expected: prints `Backfill request sent for <N> ids ...` where N matches the current line count of `data/seen_jobs.json`'s array (~250).

- [ ] **Step 7: Verify the backfill landed before touching anything else**

Using the same credentials, confirm (via `mcp__plugin_supabase_supabase__execute_sql` with `select count(*) from listings;`, or a quick Python one-liner calling `db.load_seen_keys(...)`) that the row count matches the backfilled id count from Step 6.
Expected: row count == the N printed in Step 6. Do not proceed to Step 8 until this matches — this is the ordering constraint from Global Constraints: the new Supabase-backed `main.py` must never run for real against an empty `listings` table.

- [ ] **Step 8: Delete the old dedup file and its data**

```bash
rm pipeline/dedup.py
rm pipeline/data/seen_jobs.json
rmdir pipeline/data 2>/dev/null || true
```

- [ ] **Step 9: Update the workflow — add Supabase secrets, drop the git-commit step**

`.github/workflows/daily.yml`:
```yaml
name: Daily Job Hunter

on:
  schedule:
    - cron: "0 8 * * *"
  workflow_dispatch: {}

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    environment: env
    defaults:
      run:
        working-directory: pipeline
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Write cv.json from secret
        env:
          CV_JSON: ${{ secrets.CV_JSON }}
        run: echo "$CV_JSON" > cv.json

      - name: Run pipeline
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          JEV_API_KEY: ${{ secrets.JEV_API_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          MATCH_THRESHOLD: ${{ vars.MATCH_THRESHOLD }}
        run: python main.py

      - name: Notify on failure
        if: failure()
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d text="⚠️ job-hunter-agent: el pipeline falló. Logs: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}"
```

Also add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` as secrets on the `env` Environment in GitHub (Settings -> Environments -> env -> Secrets), using the values from Task 2 — this workflow change is inert until those exist.

- [ ] **Step 10: Update `pipeline/tests/test_workflow.py`**

```python
from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "daily.yml"


def test_workflow_yaml_is_valid_and_scheduled_daily():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    triggers = parsed[True]
    assert triggers["schedule"][0]["cron"] == "0 8 * * *"
    assert "workflow_dispatch" in triggers

    job = parsed["jobs"]["run-pipeline"]
    assert job["defaults"]["run"]["working-directory"] == "pipeline"
    assert job["environment"] == "env"


def test_workflow_uses_required_secrets():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for secret_name in (
        "DEEPSEEK_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "CV_JSON",
        "JEV_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        assert f"secrets.{secret_name}" in content


def test_workflow_passes_match_threshold_variable():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "vars.MATCH_THRESHOLD" in content


def test_workflow_notifies_telegram_on_failure():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    steps = parsed["jobs"]["run-pipeline"]["steps"]
    failure_steps = [step for step in steps if step.get("if") == "failure()"]

    assert len(failure_steps) == 1
    failure_step = failure_steps[0]
    assert "sendMessage" in failure_step["run"]
    assert steps[-1] is failure_step


def test_workflow_no_longer_commits_seen_jobs_json():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "seen_jobs.json" not in content
```

- [ ] **Step 11: Run the full suite**

Run: `cd pipeline && pytest -v`
Expected: PASS (all tests; `dedup.py`'s absence is fine since nothing imports it anymore after Task 8)

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "chore: cut over to Supabase - remove dedup.py, seen_jobs.json, and the git-commit workflow step"
```

---

### Task 10: Dashboard — Next.js + Supabase Auth, deployed to Vercel

This task has no Python pytest suite. Its "tests" are: the app builds, login works with the real Auth user from Task 2, and the logged-in page shows real rows from `listings`.

**Files:**
- Create: `dashboard/` (full Next.js App Router project)

**Interfaces:**
- Consumes: `SUPABASE_URL`, `SUPABASE_ANON_KEY` (Task 2's output, as `NEXT_PUBLIC_*` env vars), and the `listings` table + RLS policy (Task 2).

- [ ] **Step 1: Scaffold the app**

```bash
npx create-next-app@latest dashboard --typescript --app --tailwind --no-src-dir --import-alias "@/*"
cd dashboard
npm install @supabase/supabase-js @supabase/ssr
```

- [ ] **Step 2: Add the Supabase client helpers**

`dashboard/lib/supabase/server.ts`:
```typescript
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // called from a Server Component - middleware refreshes sessions instead
          }
        },
      },
    }
  );
}
```

`dashboard/lib/supabase/client.ts`:
```typescript
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}
```

- [ ] **Step 3: Add the login page**

`dashboard/app/login/page.tsx`:
```typescript
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setError(error.message);
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <main className="flex min-h-screen items-center justify-center">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 w-80">
        <h1 className="text-xl font-semibold">job-hunter-agent</h1>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="border rounded px-3 py-2"
          required
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="border rounded px-3 py-2"
          required
        />
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <button type="submit" className="bg-black text-white rounded px-3 py-2">
          Log in
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 4: Add the listings page (server component, redirects to /login if not authenticated)**

`dashboard/app/page.tsx`:
```typescript
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import ListingsTable from "@/components/ListingsTable";

export default async function Home() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: listings, error } = await supabase
    .from("listings")
    .select("source, id, title, company, url, match_pct, notified, reasoning, draft_message, created_at")
    .order("created_at", { ascending: false });

  if (error) {
    return <main className="p-8">Failed to load listings: {error.message}</main>;
  }

  return (
    <main className="p-8">
      <h1 className="text-2xl font-semibold mb-4">job-hunter-agent</h1>
      <ListingsTable listings={listings ?? []} />
    </main>
  );
}
```

- [ ] **Step 5: Add the client-side filterable table**

`dashboard/components/ListingsTable.tsx`:
```typescript
"use client";

import { useMemo, useState } from "react";

type Listing = {
  source: string;
  id: string;
  title: string;
  company: string | null;
  url: string;
  match_pct: number | null;
  notified: boolean;
  reasoning: string | null;
  draft_message: string | null;
  created_at: string;
};

export default function ListingsTable({ listings }: { listings: Listing[] }) {
  const [source, setSource] = useState<string>("all");
  const [notifiedOnly, setNotifiedOnly] = useState(false);
  const [minMatch, setMinMatch] = useState(0);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return listings.filter((listing) => {
      if (source !== "all" && listing.source !== source) return false;
      if (notifiedOnly && !listing.notified) return false;
      if ((listing.match_pct ?? 0) < minMatch) return false;
      return true;
    });
  }, [listings, source, notifiedOnly, minMatch]);

  return (
    <div>
      <div className="flex gap-4 mb-4 items-center">
        <select value={source} onChange={(e) => setSource(e.target.value)} className="border rounded px-2 py-1">
          <option value="all">All sources</option>
          <option value="getonbrd">GetOnBoard</option>
          <option value="computrabajo">Computrabajo</option>
        </select>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={notifiedOnly}
            onChange={(e) => setNotifiedOnly(e.target.checked)}
          />
          Notified only
        </label>
        <label className="flex items-center gap-1">
          Min match %
          <input
            type="number"
            value={minMatch}
            onChange={(e) => setMinMatch(Number(e.target.value))}
            className="border rounded px-2 py-1 w-20"
          />
        </label>
      </div>

      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b">
            <th className="p-2">Source</th>
            <th className="p-2">Title</th>
            <th className="p-2">Company</th>
            <th className="p-2">Match %</th>
            <th className="p-2">Notified</th>
            <th className="p-2">Date</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((listing) => {
            const key = `${listing.source}:${listing.id}`;
            const isExpanded = expandedKey === key;
            return (
              <>
                <tr
                  key={key}
                  className="border-b cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedKey(isExpanded ? null : key)}
                >
                  <td className="p-2">{listing.source}</td>
                  <td className="p-2">
                    <a href={listing.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                      {listing.title}
                    </a>
                  </td>
                  <td className="p-2">{listing.company}</td>
                  <td className="p-2">{listing.match_pct ?? "-"}</td>
                  <td className="p-2">{listing.notified ? "yes" : "no"}</td>
                  <td className="p-2">{new Date(listing.created_at).toLocaleDateString()}</td>
                </tr>
                {isExpanded && (
                  <tr key={`${key}-detail`} className="border-b bg-gray-50">
                    <td colSpan={6} className="p-4">
                      <p><strong>Reasoning:</strong> {listing.reasoning ?? "n/a"}</p>
                      <p className="mt-2"><strong>Draft message:</strong> {listing.draft_message ?? "n/a"}</p>
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 6: Verify locally**

```bash
cd dashboard
echo "NEXT_PUBLIC_SUPABASE_URL=<from Task 2>" >> .env.local
echo "NEXT_PUBLIC_SUPABASE_ANON_KEY=<from Task 2>" >> .env.local
npm run dev
```
Open `http://localhost:3000`, confirm it redirects to `/login`, log in with the Task 2 Auth user's email/password, confirm the table renders and shows real rows (the backfill placeholders plus anything the cron has inserted since Task 9's cutover).

- [ ] **Step 7: Deploy to Vercel**

Use the Vercel MCP tools (or `vercel` CLI) to create a new project pointed at this repo with **root directory `dashboard`**, and set `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` as its environment variables (same values as Step 6). Deploy to production.

- [ ] **Step 8: Manual RLS cross-check (Review Focus item)**

Before treating this as done: in the Supabase Dashboard, temporarily create a second, throwaway Auth user, log into the deployed dashboard as that user, and confirm the table is empty (not the real user's rows). Delete the throwaway user afterward. This is the concrete verification that RLS is doing its job, not just present in the schema.

- [ ] **Step 9: Commit**

```bash
git add dashboard
git commit -m "feat: add read-only Next.js dashboard (Supabase Auth + RLS)"
```

---

### Task 11: End-to-end verification

No new files. This task is entirely verification that Tasks 1-10 work together for real.

- [ ] **Step 1: Trigger a real workflow run**

```bash
gh workflow run daily.yml --repo <owner>/job-hunter-agent
```
Wait for it to complete (`gh run watch <run-id> --repo <owner>/job-hunter-agent --exit-status`).
Expected: exit 0.

- [ ] **Step 2: Confirm new rows landed in Supabase**

Via `mcp__plugin_supabase_supabase__execute_sql` (`select count(*) from listings where created_at > now() - interval '1 hour';`) or `db.load_seen_keys(...)`, confirm the row count grew by however many new listings the sources actually returned that run.

- [ ] **Step 3: Confirm the dashboard reflects it**

Reload the deployed dashboard (logged in as the real user). Confirm the newest rows from Step 2 appear, sorted to the top by `created_at`.

- [ ] **Step 4: Confirm a deliberate failure still alerts correctly**

This only needs re-verifying if Task 1's workflow restructuring could plausibly have broken the existing failure-alert step (added before this plan) — inspect the current `.github/workflows/daily.yml` and confirm the `Notify on failure` step is still present, still last, and still has `if: failure()`. If in doubt, this was already covered by `test_workflow_notifies_telegram_on_failure` in Task 9's step 11 — re-running the full pipeline test suite once more here is sufficient, no need to force a real failure.
