from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "daily.yml"


def test_workflow_yaml_is_valid_and_scheduled_daily():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1 quirk).
    triggers = parsed[True]
    assert triggers["schedule"][0]["cron"] == "0 8 * * *"
    assert "workflow_dispatch" in triggers

    job = parsed["jobs"]["run-pipeline"]
    assert job["defaults"]["run"]["working-directory"] == "pipeline"
    assert job["environment"] == "env"
    assert parsed["permissions"]["contents"] == "write"


def test_workflow_uses_required_secrets():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for secret_name in ("DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CV_JSON", "JEV_API_KEY"):
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
    assert "secrets.TELEGRAM_BOT_TOKEN" in content
    # Must be the last step, so it can catch a failure in any earlier step
    # (dependency install, scraper, matcher/judge APIs, or the final git push).
    assert steps[-1] is failure_step
