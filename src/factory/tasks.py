"""Spec helpers: tasks.md phases (`## Phase N: title`, `- [ ] T001 ...`) and spec folders."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PHASE_RE = re.compile(r"^##\s+Phase\s+(\d+)\s*:\s*(.+?)\s*$")
TASK_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(T\d+)\b\s*(.*)$")


@dataclass(frozen=True)
class Task:
    id: str
    done: bool
    text: str


@dataclass
class Phase:
    number: int
    title: str
    tasks: list[Task] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return bool(self.tasks) and all(t.done for t in self.tasks)

    @property
    def name(self) -> str:
        return f"Phase {self.number}: {self.title}"


def parse(text: str) -> list[Phase]:
    phases: list[Phase] = []
    current: Phase | None = None
    for line in text.splitlines():
        if m := PHASE_RE.match(line):
            current = Phase(int(m.group(1)), m.group(2))
            phases.append(current)
        elif line.startswith("## ") or line.startswith("# "):
            current = None  # another top-level section ends the phase
        elif current is not None and (m := TASK_RE.match(line)):
            current.tasks.append(Task(m.group(2), m.group(1) != " ", m.group(3)))
    return phases


def find(phases: list[Phase], number: int) -> Phase | None:
    return next((p for p in phases if p.number == number), None)


def next_open(phases: list[Phase]) -> Phase | None:
    """The first phase with an unchecked task."""
    return next((p for p in phases if p.tasks and not p.done), None)


def find_spec_dir(repo: Path, feature_id: str) -> str | None:
    """The spec folder whose source.yaml records this feature id (see /factory-start)."""
    for source in sorted(repo.glob("specs/*/source.yaml")):
        data = yaml.safe_load(source.read_text()) or {}
        if str(data.get("id", "")) == feature_id:
            return source.parent.relative_to(repo).as_posix()
    return None


def feature_id(branch: str) -> str | None:
    """ENG-123 for feature/ENG-123; None for any other branch."""
    return branch.removeprefix("feature/") if branch.startswith("feature/") else None
