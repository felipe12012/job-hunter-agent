from pathlib import Path

import pytest

from sources.getonbrd import parse_listings

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "getonbrd_sample.html"


def test_parse_listings_filters_by_keyword():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    result = parse_listings(html, keywords=["python"])

    assert len(result) == 1
    listing = result[0]
    assert listing.id == "acme-python-dev"
    assert listing.title == "Python Developer"
    assert listing.company == "Acme"
    assert "Django" in listing.description


def test_parse_listings_matches_multiple_keywords():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    result = parse_listings(html, keywords=["python", "java"])

    ids = {listing.id for listing in result}
    assert ids == {"acme-python-dev", "gamma-backend-dev"}


def test_parse_listings_is_case_insensitive():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    result = parse_listings(html, keywords=["PYTHON"])

    assert len(result) == 1
    assert result[0].id == "acme-python-dev"


def test_parse_listings_raises_when_no_cards_found_at_all():
    html = "<html><body>no jobs here</body></html>"

    with pytest.raises(RuntimeError):
        parse_listings(html, keywords=["python"])
