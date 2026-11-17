from pathlib import Path

import pytest

from factory import ci
from factory.contract import load
from factory.runner import AGENT_GIT_NAME
from tests.conftest import git


def _commit(repo: Path, files: dict[str, str], message: str, author: str = "dev") -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", ".")
    git(repo, "-c", f"user.name={author}", "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD").strip()


def test_factory_step_passes_small_commits(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, {"a.txt": "1\n2\n"}, "small")
    outcome = ci.factory_step(repo, load(repo), base, "HEAD")
    assert outcome.ok


def test_factory_step_checks_each_commit_size(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, {"a.txt": "x\n" * 5}, "five lines")
    _commit(repo, {"b.txt": "x\n" * 11}, "eleven lines")
    _commit(repo, {"pnpm-lock.yaml": "x\n" * 50}, "lockfile only")
    outcome = ci.factory_step(repo, load(repo), base, "HEAD")
    assert not outcome.ok and outcome.detail == "1 problem(s)"


def test_protected_paths_only_bind_agent_commits(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, {".github/workflows/x.yml": "a\n"}, "human edits CI")
    assert ci.factory_step(repo, load(repo), base, "HEAD").ok
    _commit(repo, {"CLAUDE.md": "a\n"}, "agent edits CLAUDE.md", author=AGENT_GIT_NAME)
    assert not ci.factory_step(repo, load(repo), base, "HEAD").ok
    assert "agent changed protected path CLAUDE.md" in capsys.readouterr().out


def test_product_steps_run_contract_commands(repo: Path) -> None:
    (repo / ".factory" / "factory.yaml").write_text(
        "version: 1\nrunner: base\ncommands:\n  setup: 'true'\n  verify: 'false'\n"
    )
    outcomes = ci.run(["setup", "verify", "checks"], repo, load(repo), None)
    assert [(o.step, o.ok, o.skipped) for o in outcomes] == [
        ("setup", True, False),
        ("verify", False, False),
        ("checks", True, True),
    ]


def test_scanner_missing_outside_the_image_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ci.shutil, "which", lambda _: None)
    outcome = ci.secrets_step(repo, None, "HEAD")
    assert not outcome.ok and "not installed" in outcome.detail


@pytest.mark.parametrize("base", [None, "", ci.NULL_SHA, "no-such-ref"])
def test_resolve_base_without_a_range(repo: Path, base: str | None) -> None:
    assert ci.resolve_base(repo, base) is None


def test_resolve_base_to_a_commit(repo: Path) -> None:
    assert ci.resolve_base(repo, "HEAD") == git(repo, "rev-parse", "HEAD").strip()
