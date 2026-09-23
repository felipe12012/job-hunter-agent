import json
from pathlib import Path

from dedup import load_seen, filter_unseen, mark_seen
from models import JobListing


def make_listing(job_id: str) -> JobListing:
    return JobListing(
        id=job_id,
        title="Python Developer",
        company="Acme",
        url=f"https://www.getonbrd.com/jobs/programming/{job_id}",
        description="Build backend services in Python.",
    )


def test_load_seen_missing_file_returns_empty_set(tmp_path: Path):
    path = tmp_path / "seen_jobs.json"
    assert load_seen(path) == set()


def test_load_seen_reads_existing_ids(tmp_path: Path):
    path = tmp_path / "seen_jobs.json"
    path.write_text(json.dumps(["acme-python-dev"]), encoding="utf-8")
    assert load_seen(path) == {"acme-python-dev"}


def test_filter_unseen_drops_known_ids():
    listings = [make_listing("acme-python-dev"), make_listing("beta-backend-dev")]
    seen = {"acme-python-dev"}
    result = filter_unseen(listings, seen)
    assert [listing.id for listing in result] == ["beta-backend-dev"]


def test_mark_seen_persists_union_of_ids(tmp_path: Path):
    path = tmp_path / "seen_jobs.json"
    path.write_text(json.dumps(["acme-python-dev"]), encoding="utf-8")
    mark_seen(path, {"acme-python-dev"}, ["beta-backend-dev"])
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(saved) == ["acme-python-dev", "beta-backend-dev"]
