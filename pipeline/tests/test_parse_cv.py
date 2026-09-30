import json
from pathlib import Path

import parse_cv


class FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text


class FakeReader:
    def __init__(self, pages_text: list[str]):
        self.pages = [FakePage(text) for text in pages_text]


def test_extract_text_joins_all_pages(monkeypatch):
    monkeypatch.setattr(
        "parse_cv.PdfReader", lambda path: FakeReader(["Page one text.", "Page two text."])
    )

    result = parse_cv.extract_text("fake.pdf")

    assert result == "Page one text.\nPage two text."


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_structure_cv_parses_valid_response(monkeypatch):
    fake_content = json.dumps(
        {
            "name": "Ada Lovelace",
            "target_role": "Backend Engineer",
            "stack": ["Python", "Django"],
            "years_experience": 5,
            "summary": "Experienced backend engineer.",
        }
    )

    def fake_post(url, headers, json, timeout):
        return FakeResponse({"choices": [{"message": {"content": fake_content}}]})

    monkeypatch.setattr("parse_cv.requests.post", fake_post)

    result = parse_cv.structure_cv("some resume text", api_key="fake-key")

    assert result["name"] == "Ada Lovelace"
    assert result["stack"] == ["Python", "Django"]
    assert result["years_experience"] == 5


def test_main_writes_cv_and_backs_up_existing(monkeypatch, tmp_path):
    cv_path = tmp_path / "cv.json"
    cv_path.write_text(json.dumps({"name": "Old Placeholder"}), encoding="utf-8")

    monkeypatch.setattr(parse_cv, "extract_text", lambda pdf_path: "raw resume text")
    monkeypatch.setattr(
        parse_cv,
        "structure_cv",
        lambda text, api_key=None: {
            "name": "Ada Lovelace",
            "target_role": "Backend Engineer",
            "stack": ["Python"],
            "years_experience": 5,
            "summary": "Experienced backend engineer.",
        },
    )

    parse_cv.main("fake.pdf", cv_path=str(cv_path))

    new_cv = json.loads(cv_path.read_text(encoding="utf-8"))
    assert new_cv["name"] == "Ada Lovelace"

    backup_path = tmp_path / "cv.json.bak"
    backup_cv = json.loads(backup_path.read_text(encoding="utf-8"))
    assert backup_cv["name"] == "Old Placeholder"


def test_main_skips_backup_when_no_existing_cv(monkeypatch, tmp_path):
    cv_path = tmp_path / "cv.json"

    monkeypatch.setattr(parse_cv, "extract_text", lambda pdf_path: "raw resume text")
    monkeypatch.setattr(
        parse_cv,
        "structure_cv",
        lambda text, api_key=None: {"name": "Ada Lovelace"},
    )

    parse_cv.main("fake.pdf", cv_path=str(cv_path))

    assert json.loads(cv_path.read_text(encoding="utf-8"))["name"] == "Ada Lovelace"
    assert not (tmp_path / "cv.json.bak").exists()
