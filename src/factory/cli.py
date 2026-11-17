"""`factory` command-line interface."""

import argparse
import sys
from pathlib import Path

from factory import SPECKIT_VERSION
from factory.checks import git
from factory.checks.rules import (
    commit_size_violation,
    file_size_violations,
    protected_path_violations,
)
from factory.contract import CONTRACT_PATH, ContractError, load
from factory.init import CONSTITUTION, InitError, init_product

PLACEHOLDER = "FACTORY:"


def _warnings(root: Path) -> list[str]:
    warnings = []
    contract_text = (root / CONTRACT_PATH).read_text()
    for line in contract_text.splitlines():
        if PLACEHOLDER in line and not line.lstrip().startswith("#"):
            warnings.append(f"{CONTRACT_PATH}: placeholder still set: {line.strip()}")
    for rel in (CONSTITUTION, Path("CLAUDE.md")):
        path = root / rel
        if path.exists() and f"<!-- {PLACEHOLDER}" in path.read_text():
            warnings.append(f"{rel}: product section not filled in yet")
    return warnings


def cmd_init(args: argparse.Namespace) -> int:
    try:
        report = init_product(Path(args.path), name=args.name, speckit=not args.skip_speckit)
    except InitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for label, items in (("created", report.created), ("updated", report.updated)):
        for item in items:
            print(f"{label:8} {item}")
    for item in report.kept:
        print(f"kept     {item}")
    print(
        "\nNext: set commands in .factory/factory.yaml, fill in the product principles with "
        "/speckit-constitution, then run: factory validate"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        contract = load(root)
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in _warnings(root):
        print(f"warning: {warning}")
    print(f"ok: runner={contract.runner}, verify={contract.verify!r}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        contract = load(root)
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    failures: list[str] = [f"size limit: {v}" for v in file_size_violations(root, contract)]
    if args.base:
        changes = git.changes(root, args.base, args.head)
        if (violation := commit_size_violation(changes, contract)) is not None:
            failures.append(f"commit size: {violation}")
        if args.agent:
            protected = protected_path_violations(changes, contract)
            failures += [f"protected path changed: {path}" for path in protected]
    for failure in failures:
        print(failure, file=sys.stderr)
    if not failures:
        print("factory checks ok")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description="AI software factory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="make a repository a factory product")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.add_argument("--name", help="product name (default: folder name)")
    p_init.add_argument(
        "--skip-speckit", action="store_true", help=f"do not run specify init ({SPECKIT_VERSION})"
    )
    p_init.set_defaults(func=cmd_init)

    p_val = sub.add_parser("validate", help="validate .factory/factory.yaml")
    p_val.add_argument("--root", default=".")
    p_val.set_defaults(func=cmd_validate)

    p_chk = sub.add_parser("check", help="run the factory's generic checks")
    p_chk.add_argument("--root", default=".")
    p_chk.add_argument("--base", help="base ref for commit checks (e.g. HEAD~1)")
    p_chk.add_argument("--head", default="HEAD")
    p_chk.add_argument("--agent", action="store_true", help="also enforce protected paths")
    p_chk.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
