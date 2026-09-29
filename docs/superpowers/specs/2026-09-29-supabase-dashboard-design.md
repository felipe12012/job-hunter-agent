# Supabase-backed state + read-only dashboard — Design Spec

Date: 2026-09-29

## Purpose

Replace `data/seen_jobs.json` (a flat file committed to git by the daily cron)
with a real Supabase Postgres table, and add a read-only Next.js dashboard
(deployed on Vercel) so the user can browse historical matches instead of
only seeing them fly by in Telegram.

This is explicitly a foundation step for a longer-term direction the user
named: multi-user signup, CV upload per user, subscriptions, preferences.
None of that ships now — but the schema and auth model are chosen so that
work extends this table and these RLS policies rather than replacing them.

## Scope

- v1 dashboard is read-only: browse/filter listings. No mutations (no
  "mark as applied", no CV upload) — explicitly out of scope for this spec.
- Single real user (the project owner) authenticates via Supabase Auth
  (email/password). Multi-user signup is out of scope.
- One Supabase project, dedicated to job-hunter-agent (not shared with the
  user's other Supabase projects).
- The existing pipeline (scrapers -> Jev -> DeepSeek -> Telegram) is
  unchanged in behavior; only where it persists dedup/result state changes.

## Architecture

```
GitHub Actions (cron, daily)
  -> sources/getonbrd.py + sources/computrabajo.py (scrapers)
  -> judge.py (Jev, cheap true/false pre-filter)
  -> matcher.py (DeepSeek, only for Jev-approved listings)
  -> db.py (Supabase Postgres, via service_role key - replaces dedup.py)
  -> notifier.py (Telegram, unchanged)

Next.js dashboard (Vercel)
  -> Supabase Auth (email/password login, @supabase/ssr)
  -> reads `listings` via the anon/publishable key
  -> Postgres RLS restricts SELECT to the logged-in user's own rows
```

Two different Supabase credentials, two different trust levels:
- **service_role key** — used only by the GitHub Actions cron (server-side
  secret, bypasses RLS). It is the only thing allowed to write rows.
- **anon/publishable key** — used by the Next.js dashboard, safe to expose
  in client-side code. RLS is the only thing standing between this key and
  another user's rows, so RLS must be correct before this ships.

## Schema

```sql
create table listings (
  source text not null,                      -- 'getonbrd' | 'computrabajo'
  id text not null,                           -- raw id from that source's scraper
  title text not null,
  company text,
  url text not null,
  description text,
  judge_result boolean not null,              -- Jev's decision
  match_pct integer,                          -- null unless judge_result = true and DeepSeek succeeded
  reasoning text,                             -- null unless match_pct is set
  draft_message text,                         -- null unless match_pct is set
  notified boolean not null default false,    -- true once included in a sent Telegram digest
  created_at timestamptz not null default now(),
  user_id uuid not null,                      -- fixed to the project owner's Supabase Auth user for v1
  primary key (source, id)
);

alter table listings enable row level security;

create policy "users read their own listings"
  on listings for select
  using (auth.uid() = user_id);
```

`(source, id)` as the primary key is deliberate: GetOnBoard ids are
human-readable slugs, Computrabajo ids are 32-character hex strings from
`data-id` — collision between the two is not realistically possible, but a
composite key documents the actual uniqueness guarantee instead of relying
on that being true forever, and it removes any need for ad-hoc string
concatenation (`f"{source}:{id}"`) in application code.

`user_id` is `not null` from day one — a single fixed UUID (the project
owner's Supabase Auth user, created as part of this work) rather than left
nullable "for later." A nullable column with no writer ever populating it
is dead weight; a real value from day one means the RLS policy is exercised
for real immediately, not first tested when a second user shows up.

## Data Flow (per listing, inside the existing per-listing loop in main.py)

1. `judge.py` scores the listing. If it errors (`None`), skip — no row
   written, retried next run (unchanged from today's semantics).
2. If Jev rejects it (`False`), write one row: `judge_result=false`,
   `match_pct`/`reasoning`/`draft_message` all `null`. This row's existence
   *is* the dedup marker — no separate "mark seen" step.
3. If Jev approves it (`True`), call `matcher.py`. If DeepSeek errors
   (`None`), skip entirely — no row written, retried next run (this
   deliberately means Jev also re-runs for it tomorrow; the alternative,
   writing a partial `judge_result=true` row with null score fields, would
   dedupe the listing forever without ever actually scoring it, which is
   worse).
4. If DeepSeek succeeds, write one row with the full result,
   `notified=false`.
5. After all listings are processed, `notifier.py` picks the top 3
   qualifying (`match_pct >= threshold`) exactly as today. Once
   `send_digest` succeeds, `db.py` runs one
   `UPDATE listings SET notified = true WHERE (source, id) IN (...)`
   for exactly the ids that were actually sent.

Writing a row per listing (step 2/4) rather than batching everything until
the end means a crash partway through a run doesn't lose already-processed
listings — they simply won't be re-processed tomorrow, which is correct.

## Components

### `db.py` (replaces `dedup.py`)

Same calling shape as the file it replaces, so `main.py`'s control flow
barely changes:

- `load_seen_keys() -> set[tuple[str, str]]` — `GET` the `(source, id)`
  pairs from `listings` via Supabase's REST API (PostgREST), using the
  service_role key. Mirrors `dedup.py`'s old `load_seen`.
- `filter_unseen(listings: list[JobListing], seen_keys: set[tuple[str, str]]) -> list[JobListing]`
  — pure function, unchanged logic from today's `dedup.py`, just keyed on
  `(listing.source, listing.id)` instead of a bare id.
- `insert_listing(listing, judge_result, match_pct=None, reasoning=None, draft_message=None) -> None`
  — `POST` one row. Raises on failure (network/HTTP error); `main.py`
  catches it per-listing, logs, and treats that listing as unprocessed
  (same retry-next-run semantics as every other stage failure in this
  pipeline).
- `mark_notified(keys: list[tuple[str, str]]) -> None` — one `PATCH`
  request setting `notified=true` for the given `(source, id)` pairs.

Implemented with plain `requests` against Supabase's PostgREST endpoint
(`https://<project>.supabase.co/rest/v1/listings`), not the `supabase-py`
SDK — consistent with how `matcher.py`, `judge.py`, and `notifier.py` are
already written in this project, and equally mockable in tests via
`monkeypatch.setattr("db.requests.post", ...)`.

### `models.py`

`JobListing` gains one field: `source: str`. Both scraper modules already
know which source they are; each sets it when constructing `JobListing`
(`sources/getonbrd.py` sets `"getonbrd"`, `sources/computrabajo.py` sets
`"computrabajo"`). No other field changes.

### `main.py`

- Drops `SEEN_JOBS_PATH`, `load_seen`/`filter_unseen`/`mark_seen` imports
  from `dedup` — imports the equivalents from `db` instead.
- The per-listing loop now calls `db.insert_listing(...)` at the two
  terminal points described in Data Flow, instead of appending to a
  `processed_ids` list.
- Tracks a `processed_count` instead of `processed_ids` for the existing
  "all listings failed to process" check (`if unseen and processed_count == 0`).
- After `send_digest` succeeds, calls `db.mark_notified(...)` with the keys
  of whatever `notifier.py` actually sent (`notifier.send_digest` needs to
  return which listings it sent, not just `True`/`False` — see below).

### `notifier.py`

`send_digest` currently returns `bool`. It needs to return the list of
`(source, id)` pairs it actually sent (empty list = nothing sent, same
meaning as today's `False`) so `main.py` knows exactly which rows to mark
`notified=true`. This is the one behavior change to an existing module in
this spec.

### One-time backfill (migration, not part of the ongoing pipeline)

The ~250 ids already in the current `data/seen_jobs.json` need to land in
`listings` before the cutover, or the very first Supabase-backed run will
re-process and re-notify all of them. A one-off script (run once, by hand,
not committed as a permanent tool):
- Reads the existing `data/seen_jobs.json`.
- Classifies each id's `source` heuristically: Computrabajo ids match
  `^[0-9A-F]{32}$`; everything else is `getonbrd` (the only two sources
  that exist today).
- Inserts one placeholder row per id: `judge_result=false`, all score
  fields `null`, `title="(backfill placeholder)"`. `url` is
  `https://www.getonbrd.com/jobs/programming/{id}` for GetOnBoard ids
  (reconstructable since the id *is* that URL's slug) and
  `https://cl.computrabajo.com/backfill/{id}` for Computrabajo ids (not a
  real working link — Computrabajo ids are opaque hashes, the real URL
  was never captured in the old flat-file format). These rows exist
  purely to satisfy the dedup check, not to be meaningful dashboard data.
  The dashboard should filter out this backfill batch by `created_at` if
  it turns out to be visually noisy; that's a follow-up nicety, not a
  blocker.
- After this runs successfully once, `data/seen_jobs.json` and `dedup.py`
  are deleted, and `.github/workflows/daily.yml`'s "Commit updated
  seen_jobs.json" step is removed (there is nothing left for it to
  commit).

### Dashboard (`dashboard/` subfolder, Next.js, deployed to Vercel)

- Same repo, new top-level subfolder — Vercel's project settings point at
  `dashboard/` as the root directory, so this stays one repo instead of
  splitting into a second one (avoids repeating the earlier
  monorepo-vs-standalone confusion from this same project).
- Auth: Supabase Auth email/password via `@supabase/ssr`'s standard
  Next.js App Router pattern (server-side session, not a client-only
  hack). One real user account, created as part of this work.
- Single page: a table of `listings` (source, title, company, match_pct,
  notified, created_at), newest first. Client-side filters: by source, a
  "notified only" toggle, a minimum match_pct slider/input. Clicking a row
  expands `reasoning` and `draft_message`.
- Data access: browser-side Supabase client using
  `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` (Vercel env
  vars) + the logged-in session; RLS does the actual access control. No
  custom API route needed for v1 since there are no mutations.

## Error Handling

- `db.insert_listing` failure for one listing: log to stderr, that
  listing is simply not persisted this run — naturally retried next run
  since it never became "seen." No change needed to the existing
  "all listings failed to process" abort check; a listing whose DB write
  failed just doesn't count toward `processed_count`, same as a Jev or
  DeepSeek failure today.
- `db.mark_notified` failure: log to stderr. The affected listings stay
  `notified=false` in the table even though Telegram did receive them —
  a cosmetic dashboard inconsistency, not a functional problem (Telegram
  already got the message; the row's existence still prevents
  re-notification since dedup is keyed on the row existing at all, not on
  `notified`). Does not fail the run.
- `db.load_seen_keys` failure (can't reach Supabase at all): this is
  equivalent to today's total scraper failure — `main.py` should treat it
  as fatal (return 1) rather than silently treating everything as unseen
  and re-processing/re-notifying the whole backlog.

## Testing

- `db.py`: unit tests mocking `requests.get`/`post`/`patch`, following the
  exact pattern already used in `test_matcher.py`/`test_judge.py` — no
  live network calls, no real Supabase project touched by the test suite.
- `models.py`: extend the existing dataclass field test to cover `source`.
- `sources/getonbrd.py` / `sources/computrabajo.py`: existing fixture
  tests updated to assert the new `source` field on returned `JobListing`s.
- `notifier.py`: existing tests updated for the new return type (list of
  sent keys instead of bool); add a case asserting the empty-list return
  when nothing qualifies.
- `main.py`: existing tests updated to monkeypatch `db.insert_listing` /
  `db.mark_notified` instead of the old dedup functions; behavior assertions
  (retry-on-failure, abort-when-all-fail) stay conceptually the same.
- Dashboard: no automated test suite for v1 (small, read-only, single
  page) — verified by deploying to Vercel and checking it renders real
  data after login. If it grows past this, testing strategy gets revisited
  then, not speculatively now.

## Out of Scope (this spec)

- Multi-user signup, per-user CV upload, subscriptions, preferences —
  explicitly deferred by the user ("por ahora solo la opción 1"). The
  schema (`user_id`) and auth model (Supabase Auth + RLS) are chosen so
  this later work extends them rather than replacing them.
- Any dashboard mutation (mark as applied, hide a listing, etc.).
- Backfilling real historical `title`/`description`/`match_pct` for the
  ~250 already-seen listings — the backfill only needs to satisfy dedup,
  not recreate history that was never captured.
