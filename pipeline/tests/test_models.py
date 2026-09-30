from models import JobListing, ScoredListing


def make_listing() -> JobListing:
    return JobListing(
        id="acme-python-dev",
        title="Python Developer",
        company="Acme",
        url="https://www.getonbrd.com/jobs/programming/acme-python-dev",
        description="Build backend services in Python.",
    )


def test_job_listing_fields():
    job = make_listing()
    assert job.id == "acme-python-dev"
    assert job.title == "Python Developer"
    assert job.company == "Acme"


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
