from pathlib import Path

import pytest

from sources.computrabajo import parse_description, parse_listing_summaries

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "computrabajo_sample.html"
DETAIL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "computrabajo_detail_sample.html"


def test_parse_listing_summaries_extracts_all_cards():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    summaries = parse_listing_summaries(html)

    assert len(summaries) == 3
    ids = {s["id"] for s in summaries}
    assert ids == {"CT-001", "CT-002", "CT-003"}


def test_parse_listing_summaries_extracts_title_company_and_absolute_url():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    summaries = parse_listing_summaries(html)

    first = next(s for s in summaries if s["id"] == "CT-001")
    assert first["title"] == "Desarrollador Python Django"
    assert first["company"] == "Acme"
    assert first["url"] == (
        "https://cl.computrabajo.com/ofertas-de-trabajo/"
        "oferta-de-trabajo-de-desarrollador-python-django-CT-001"
    )


def test_parse_listing_summaries_raises_when_no_cards_found_at_all():
    html = "<html><body>no jobs here</body></html>"

    with pytest.raises(RuntimeError):
        parse_listing_summaries(html)


def test_parse_description_extracts_body_and_requirements():
    html = DETAIL_FIXTURE_PATH.read_text(encoding="utf-8")
    description = parse_description(html)

    assert "Django" in description
    assert "APIs REST" in description
    assert "3 años de experiencia" in description


def test_parse_description_returns_empty_string_when_section_missing():
    description = parse_description("<html><body>no description here</body></html>")

    assert description == ""
