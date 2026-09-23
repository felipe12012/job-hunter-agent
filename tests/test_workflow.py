from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "daily.yml"


def test_workflow_yaml_is_valid_and_scheduled_daily():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1 quirk).
    triggers = parsed[True]
    assert triggers["schedule"][0]["cron"] == "0 8 * * *"
    assert "workflow_dispatch" in triggers

    job = parsed["jobs"]["run-pipeline"]
    assert "defaults" not in job
    assert parsed["permissions"]["contents"] == "write"


def test_workflow_uses_required_secrets():
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for secret_name in ("DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        assert f"secrets.{secret_name}" in content
