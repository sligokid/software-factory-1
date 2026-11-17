"""Fail if governed files exceed their line limits (factory/limits.toml)."""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMITS = ROOT / "factory" / "limits.toml"


def find_violations(root: Path = ROOT, limits_path: Path = LIMITS) -> list[str]:
    limits: dict[str, int] = tomllib.loads(limits_path.read_text())["files"]
    violations = []
    for pattern, limit in limits.items():
        for path in sorted(root.glob(pattern)):
            lines = len(path.read_text().splitlines())
            if lines > limit:
                violations.append(f"{path.relative_to(root)}: {lines} lines (limit {limit})")
    return violations


def main() -> int:
    violations = find_violations()
    for violation in violations:
        print(f"size limit exceeded: {violation}", file=sys.stderr)
    if not violations:
        print("size limits ok")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
