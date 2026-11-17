"""Contract-driven rules: file size limits, commit size and protected paths."""

from collections.abc import Iterator
from pathlib import Path

from factory.checks.git import FileChange
from factory.checks.globs import matches, matches_any
from factory.contract import Contract

SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "build", "__pycache__"}


def _files(root: Path) -> Iterator[Path]:
    for path in sorted(root.iterdir()):
        if path.is_dir():
            if path.name not in SKIP_DIRS:
                yield from _files(path)
        elif path.is_file():
            yield path


def file_size_violations(root: Path, contract: Contract) -> list[str]:
    """Governed files (e.g. CLAUDE.md, the constitution) over their line limits."""
    violations = []
    for path in _files(root):
        rel = path.relative_to(root).as_posix()
        for pattern, limit in contract.file_limits.items():
            if matches(rel, pattern):
                lines = len(path.read_text(errors="replace").splitlines())
                if lines > limit:
                    violations.append(f"{rel}: {lines} lines (limit {limit})")
    return violations


def commit_size_violation(changes: list[FileChange], contract: Contract) -> str | None:
    """A single phase commit over the changed-line limit (excluded paths not counted)."""
    counted = sum(c.lines for c in changes if not matches_any(c.path, contract.exclude))
    if counted > contract.commit_lines:
        limit = contract.commit_lines
        return f"{counted} changed lines (limit {limit}, excluding {contract.exclude})"
    return None


def protected_path_violations(changes: list[FileChange], contract: Contract) -> list[str]:
    """Agent changes to paths only humans may change."""
    return [c.path for c in changes if matches_any(c.path, contract.protected)]
