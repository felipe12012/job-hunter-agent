from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "daily.yml"


def test_workflow_yaml_is_valid_and_scheduled_daily():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    triggers = parsed[True]
    assert triggers["schedule"][0]["cron"] == "0 8 * * *"
    assert "workflow_dispatch" in triggers

    job = parsed["jobs"]["run-pipeline"]
    assert job["defaults"]["run"]["working-directory"] == "pipeline"
    assert job["environment"] == "env"


def test_workflow_uses_required_secrets():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for secret_name in (
        "DEEPSEEK_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "CV_JSON",
        "JEV_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "BACKFILL_USER_ID",
    ):
        assert f"secrets.{secret_name}" in content


def test_workflow_passes_match_threshold_variable():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "vars.MATCH_THRESHOLD" in content


def test_workflow_notifies_telegram_on_failure():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    steps = parsed["jobs"]["run-pipeline"]["steps"]
    failure_steps = [step for step in steps if step.get("if") == "failure()"]

    assert len(failure_steps) == 1
    failure_step = failure_steps[0]
    assert "sendMessage" in failure_step["run"]
    assert steps[-1] is failure_step


def test_workflow_no_longer_commits_seen_jobs_json():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "seen_jobs.json" not in content
