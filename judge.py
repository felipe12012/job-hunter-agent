import json
import os
import sys

import requests

from models import JobListing

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"

STATE_TEMPLATE = """Candidate CV:
{cv}

Job title: {job_title}
Company: {company}
Job description:
{job_description}
"""

MATCH_INSTRUCTIONS = (
    "The candidate's CV is a strong enough match for this job's requirements to justify "
    "sending a personalized outreach message (roughly an 80%+ fit)."
)


def is_strong_match(listing: JobListing, cv: dict, api_key: str | None = None) -> bool | None:
    api_key = api_key or os.environ.get("JEV_API_KEY")
    state = STATE_TEMPLATE.format(
        cv=json.dumps(cv),
        job_title=listing.title,
        company=listing.company,
        job_description=listing.description,
    )

    try:
        response = requests.post(
            TYPESAFE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "state": state,
                "model": "jev-latest",
                "questions": {
                    "is_strong_match": {
                        "type": "noul",
                        "instructions": MATCH_INSTRUCTIONS,
                    }
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        noul_value = response.json()["answers"]["is_strong_match"]["noul"]
        return float(noul_value) >= 0.5
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError, IndexError, TypeError) as exc:
        print(f"is_strong_match failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
