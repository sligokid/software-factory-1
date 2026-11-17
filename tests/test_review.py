import json
import os
import stat
from pathlib import Path

import pytest

from factory import review
from factory.contract import load
from tests.conftest import git

OUTPUT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 4,
    "total_cost_usd": 0.2,
    "structured_output": {
        "summary": "Adds app.txt.",
        "findings": [
            {"severity": "advisory", "rule": "General", "message": "name | it better"},
            {
                "severity": "blocking",
                "rule": "Factory: Spec and Task Rules",
                "file": "app.txt",
                "line": 1,
                "message": "no tests",
            },
        ],
    },
}


def test_prompt_names_commits_spec_constitution_and_screenshots(
    product: Path, tmp_path: Path
) -> None:
    base = git(product, "rev-parse", "HEAD~1").strip()
    shot = tmp_path / "root-desktop.png"
    prompt = review.build_prompt(product, load(product), base, "HEAD", "specs/001-demo", [shot])
    assert "DEMO-1: spec" in prompt
    assert ".specify/memory/constitution.md" in prompt
    assert "specs/001-demo/spec.md" in prompt
    assert str(shot) in prompt
    assert f"git diff {base}...HEAD" in prompt


def test_reviewer_is_read_only(product: Path, tmp_path: Path) -> None:
    cmd = review.claude_command("p", load(product), max_turns=3, model=None, extra_dirs=[tmp_path])
    allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")]
    denied = cmd[cmd.index("--disallowedTools") + 1 :]
    assert not {"Edit", "Write", "MultiEdit"} & set(allowed)
    assert {"Edit", "Write", "Bash(git commit*)", "Bash(git push*)"} <= set(denied)
    assert cmd[cmd.index("--add-dir") + 1] == str(tmp_path)
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == review.SCHEMA


def test_parse_output_and_verdict() -> None:
    result = review.parse_output(json.dumps(OUTPUT), "a" * 40, "b" * 40)
    assert not result.passed and len(result.blocking) == 1
    assert result.as_dict()["verdict"] == "fail"
    assert result.usage["num_turns"] == 4
    text = review.markdown(result)
    assert "changes required" in text and "1 blocking · 1 advisory" in text
    assert text.index("no tests") < text.index("name \\| it better")  # blocking first, escaped
    assert "`app.txt:1`" in text


@pytest.mark.parametrize(
    "stdout",
    ["not json", json.dumps({"is_error": True, "subtype": "error_max_turns"}), json.dumps({})],
)
def test_parse_output_without_verdict_is_an_error(stdout: str) -> None:
    with pytest.raises(review.ReviewError):
        review.parse_output(stdout, "a", "b")


def test_review_runs_claude_and_refuses_api_keys(
    product: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "claude"
    fake.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(OUTPUT)}\nEOF\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = review.review(product, load(product), "HEAD~1", "HEAD")
    assert result.summary == "Adds app.txt." and not result.passed
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    with pytest.raises(review.ReviewError, match="ANTHROPIC_API_KEY"):
        review.review(product, load(product), "HEAD~1", "HEAD")
