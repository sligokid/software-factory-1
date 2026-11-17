"""The runner entrypoint end to end, with a fake `claude` on PATH (no Docker, no network)."""

import base64
import io
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from factory.runner import INPUT_REF, entrypoint
from tests.conftest import git

FAKE_CLAUDE = """#!/usr/bin/env python3
import os, pathlib, subprocess, sys
action = os.environ["FAKE_CLAUDE"]
tasks = pathlib.Path("specs/001-demo/tasks.md")
text = tasks.read_text()
if action in ("implement", "overreach"):
    pathlib.Path("app.txt").write_text("hello\\n")
    text = text.replace("- [ ] T001", "- [X] T001").replace("- [ ] T002", "- [X] T002")
    if action == "overreach":
        text = text.replace("- [ ] T003", "- [X] T003")
    tasks.write_text(text)
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "wip"], check=True)
    pathlib.Path("extra.txt").write_text("uncommitted work is kept\\n")
elif action == "protected":
    pathlib.Path("CLAUDE.md").write_text("changed\\n")
    pathlib.Path("app.txt").write_text("hello\\n")
    tasks.write_text(text.replace("- [ ] T001", "- [X] T001").replace("- [ ] T002", "- [X] T002"))
print('{"type": "result", "num_turns": 3}')
"""


@pytest.fixture
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("run")


def _run(
    product: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, **env: str
) -> tuple[int, dict[str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(product, "update-ref", INPUT_REF, "HEAD")
    bundle = tmp_path / "in.bundle"
    git(product, "bundle", "create", "-q", str(bundle), INPUT_REF)
    git(product, "update-ref", "-d", INPUT_REF)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    for key in entrypoint.REFUSED_ENV:
        monkeypatch.delenv(key, raising=False)
    values = {
        "CLAUDE_CODE_OAUTH_TOKEN": "token",
        "FACTORY_MODE": "implement",
        "FACTORY_BRANCH": "feature/DEMO-1",
        "FACTORY_WORKSPACE": str(workspace),
        "FAKE_CLAUDE": action,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        **env,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(bundle.read_bytes())))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = entrypoint.main()
    record = json.loads(out.getvalue().splitlines()[-1])
    return code, record


def test_implement_phase_delivers_one_commit(
    product: Path, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = git(product, "rev-parse", "HEAD").strip()
    code, record = _run(product, work, monkeypatch, "implement")
    assert code == 0, record
    assert record["status"] == "ok" and record["phase"] == 1 and record["base"] == base
    bundle = work / "out.bundle"
    bundle.write_bytes(base64.b64decode(str(record["bundle"])))
    git(product, "fetch", "-q", str(bundle), "refs/heads/feature/DEMO-1:refs/factory/result")
    log = git(product, "log", "--format=%s", f"{base}..refs/factory/result").splitlines()
    assert log == ["DEMO-1: Phase 1: Setup"]
    files = git(product, "show", "--name-only", "--format=", "refs/factory/result").split()
    assert sorted(files) == ["app.txt", "extra.txt", "specs/001-demo/tasks.md"]


def test_checking_tasks_of_another_phase_fails(
    product: Path, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, record = _run(product, work, monkeypatch, "overreach")
    assert code == entrypoint.EXIT_FAILED
    assert "outside Phase 1" in str(record["reason"])


def test_protected_path_change_fails(
    product: Path, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, record = _run(product, work, monkeypatch, "protected")
    assert code == entrypoint.EXIT_FAILED
    assert "protected path changed: CLAUDE.md" in str(record["log"])


def test_no_changes_fails_implement_but_means_converged(
    product: Path, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, record = _run(product, work, monkeypatch, "nothing")
    assert code == entrypoint.EXIT_FAILED and record["reason"] == "the agent made no changes"
    code, record = _run(product, work / "again", monkeypatch, "nothing", FACTORY_MODE="converge")
    assert code == 0 and record["converged"] is True


def test_api_key_stops_the_run(product: Path, work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, record = _run(product, work, monkeypatch, "implement", ANTHROPIC_API_KEY="sk-x")
    assert code == entrypoint.EXIT_REFUSED and record["status"] == "refused"


@pytest.mark.parametrize(
    ("env", "error"),
    [
        ({"CLAUDE_CODE_OAUTH_TOKEN": "t", "ANTHROPIC_API_KEY": ""}, "ANTHROPIC_API_KEY"),
        ({}, "CLAUDE_CODE_OAUTH_TOKEN is required"),
        ({"CLAUDE_CODE_OAUTH_TOKEN": "t"}, None),
    ],
)
def test_credentials(env: dict[str, str], error: str | None) -> None:
    result = entrypoint.credentials_error(env)
    assert result == error if error is None else error in str(result)


def test_config_rejects_bad_branch() -> None:
    with pytest.raises(entrypoint.RunError, match="feature/<ID>"):
        entrypoint.Config.from_env({"FACTORY_MODE": "implement", "FACTORY_BRANCH": "main"})
