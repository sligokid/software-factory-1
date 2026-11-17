"""Create a new slice from factory/templates/slice (*.tmpl files are rendered without suffix)."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "factory" / "templates" / "slice"
SLICES = ROOT / "src" / "slices"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def create_slice(name: str, slices_dir: Path = SLICES) -> Path:
    if not NAME_RE.match(name):
        raise ValueError(f"invalid slice name {name!r}: use snake_case, 2-40 chars")
    target = slices_dir / name
    if target.exists():
        raise FileExistsError(f"slice {name!r} already exists at {target}")
    for source in TEMPLATE.rglob("*"):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        relative = source.relative_to(TEMPLATE)
        if relative.suffix == ".tmpl":
            relative = relative.with_suffix("")
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source.read_text().replace("{{slice}}", name))
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m factory.new_slice <name>", file=sys.stderr)
        return 2
    path = create_slice(argv[0])
    print(f"created {path.relative_to(ROOT)}; register its router in src/app/registry.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
