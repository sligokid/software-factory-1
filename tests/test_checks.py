from pathlib import Path

import pytest

from factory.checks import git
from factory.checks.globs import matches
from factory.checks.rules import (
    commit_size_violation,
    file_size_violations,
    protected_path_violations,
)
from factory.cli import main
from factory.contract import load

from .conftest import git as run_git


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        (".github/workflows/ci.yml", ".github/**", True),
        ("CLAUDE.md", "CLAUDE.md", True),
        ("docs/CLAUDE.md", "CLAUDE.md", True),
        ("web/pnpm-lock.yaml", "pnpm-lock.yaml", True),
        ("specs/001-x/spec.md", "specs/**", True),
        ("src/specs.py", "specs/**", False),
        ("src/generated/a/b.ts", "src/**/b.ts", True),
        ("src/app.py", "*.ts", False),
    ],
)
def test_globs(path: str, pattern: str, expected: bool) -> None:
    assert matches(path, pattern) is expected


def test_file_size_limits(repo: Path) -> None:
    (repo / "CLAUDE.md").write_text("x\n" * 121)
    assert file_size_violations(repo, load(repo)) == ["CLAUDE.md: 121 lines (limit 120)"]


def test_commit_size_excludes_lock_and_specs(repo: Path) -> None:
    (repo / "pnpm-lock.yaml").write_text("x\n" * 500)
    (repo / "specs").mkdir()
    (repo / "specs" / "tasks.md").write_text("x\n" * 500)
    (repo / "app.ts").write_text("x\n" * 10)
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "phase")
    changes = git.changes(repo, "HEAD~1")
    assert commit_size_violation(changes, load(repo)) is None

    (repo / "app.ts").write_text("y\n" * 11)
    run_git(repo, "commit", "-q", "-am", "too big")
    violation = commit_size_violation(git.changes(repo, "HEAD~1"), load(repo))
    assert violation is not None and violation.startswith("21 changed lines")


def test_protected_paths(repo: Path) -> None:
    (repo / ".github").mkdir()
    (repo / ".github" / "ci.yml").write_text("on: push\n")
    (repo / "app.ts").write_text("ok\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "agent")
    assert protected_path_violations(git.changes(repo, "HEAD~1"), load(repo)) == [".github/ci.yml"]


def test_cli_check(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--root", str(repo)]) == 0
    (repo / ".claude").mkdir()
    (repo / ".claude" / "x.md").write_text("x\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "agent")
    assert main(["check", "--root", str(repo), "--base", "HEAD~1"]) == 0
    assert main(["check", "--root", str(repo), "--base", "HEAD~1", "--agent"]) == 1
    assert "protected path changed: .claude/x.md" in capsys.readouterr().err
