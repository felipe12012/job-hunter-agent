import json
import os
import sys

import requests

from models import JobListing, ScoredListing

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

PROMPT_TEMPLATE = """You are an experienced technical recruiter. Compare the candidate's \
CV against the job description below and respond with ONLY a JSON object with these \
exact keys: match_pct (integer 0-100), reasoning (short string explaining the score), \
draft_message (a short, specific outreach message the candidate could send to the \
recruiter for this role, in the candidate's own voice).

CV:
{cv}

Job title: {job_title}
Company: {company}
Job description:
{job_description}
"""


def load_cv(path: str = "cv.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def score_listing(listing: JobListing, cv: dict, api_key: str | None = None) -> ScoredListing | None:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    prompt = PROMPT_TEMPLATE.format(
        cv=json.dumps(cv),
        job_title=listing.title,
        company=listing.company,
        job_description=listing.description,
    )

    try:
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
        parsed = json.loads(content)
        return ScoredListing(
            listing=listing,
            match_pct=int(parsed["match_pct"]),
            reasoning=str(parsed["reasoning"]),
            draft_message=str(parsed["draft_message"]),
        )
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError, IndexError, TypeError) as exc:
        print(f"score_listing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
