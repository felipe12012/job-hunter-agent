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
