import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "test")
    (tmp_path / ".factory").mkdir()
    (tmp_path / ".factory" / "factory.yaml").write_text(
        "version: 1\nrunner: node\ncommands:\n  verify: pnpm test\n"
        "limits:\n  commit_lines: 10\n  exclude: [pnpm-lock.yaml]\n"
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


DEMO_TASKS = """# Tasks
## Phase 1: Setup
- [ ] T001 Create app.txt
- [ ] T002 Fill app.txt
## Phase 2: More
- [ ] T003 Later
"""


@pytest.fixture
def product(repo: Path) -> Path:
    """A product on branch feature/DEMO-1 with a two-phase spec; verify needs app.txt."""
    (repo / ".factory" / "factory.yaml").write_text(
        "version: 1\nrunner: base\ncommands:\n  setup: 'true'\n  verify: test -f app.txt\n"
    )
    spec = repo / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "source.yaml").write_text("type: document\nid: DEMO-1\ntitle: Demo\n")
    (spec / "tasks.md").write_text(DEMO_TASKS)
    (repo / "CLAUDE.md").write_text("# guide\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "DEMO-1: spec")
    git(repo, "switch", "-qc", "feature/DEMO-1")
    return repo
