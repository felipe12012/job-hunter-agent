import json
import os
import shutil
import sys
from pathlib import Path

import requests
from pypdf import PdfReader

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

PROMPT_TEMPLATE = """You are an expert CV/resume parser. Read the raw resume text below and \
extract a structured JSON object with EXACTLY these keys: name (string), target_role (string, \
the role this person is best suited for based on their experience), stack (array of strings, \
the technologies/skills mentioned), years_experience (integer, total years of professional \
experience), summary (string, a 2-3 sentence summary of their background and strengths, in \
Spanish). Respond with ONLY the JSON object, no other text.

Resume text:
{text}
"""


def extract_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages_text)


def structure_cv(text: str, api_key: str | None = None) -> dict:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    prompt = PROMPT_TEMPLATE.format(text=text)

    response = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def main(pdf_path: str, cv_path: str = "cv.json") -> None:
    text = extract_text(pdf_path)
    cv = structure_cv(text)

    cv_file = Path(cv_path)
    if cv_file.exists():
        backup_path = cv_file.with_name(cv_file.name + ".bak")
        shutil.copy(cv_file, backup_path)

    with cv_file.open("w", encoding="utf-8") as f:
        json.dump(cv, f, indent=2, ensure_ascii=False)

    print(f"CV parsed and written to {cv_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_cv.py <path-to-cv.pdf>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
