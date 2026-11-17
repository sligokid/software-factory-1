"""Small git helpers for diff-based checks."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileChange:
    path: str
    added: int
    deleted: int

    @property
    def lines(self) -> int:
        return self.added + self.deleted


def changes(repo: Path, base: str, head: str = "HEAD") -> list[FileChange]:
    """Files changed between base and head (binary files count as 0 lines)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--numstat", "--no-renames", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    result = []
    for line in out.splitlines():
        added, deleted, path = line.split("\t", 2)
        result.append(
            FileChange(
                path=path,
                added=0 if added == "-" else int(added),
                deleted=0 if deleted == "-" else int(deleted),
            )
        )
    return result


def current_branch(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    subject: str


def commits(repo: Path, base: str, head: str = "HEAD") -> list[Commit]:
    """Non-merge commits in base..head, oldest first."""
    out = subprocess.run(
        ["git", "-C", str(repo), "log", "--reverse", "--no-merges", "--format=%H%x00%an%x00%s",
         f"{base}..{head}"],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    return [Commit(*line.split("\0", 2)) for line in out.splitlines() if line]
