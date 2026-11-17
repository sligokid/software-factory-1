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
from factory.runner import Mode, host, sandbox

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


def cmd_agent(args: argparse.Namespace) -> int:
    branch = args.branch or git.current_branch(Path(args.product))
    feedback = Path(args.feedback_file).read_text() if args.feedback_file else ""
    req = host.RunRequest(
        product=Path(args.product),
        branch=branch,
        mode=Mode(args.mode),
        phase=args.phase,
        feedback=feedback,
        max_turns=args.max_turns,
        model=args.model,
        timeout=args.timeout,
        limits=sandbox.Limits(cpus=args.cpus, memory=args.memory, pids=args.pids),
        image=args.image,
        apply=not args.no_apply,
    )
    return host.agent(req, Path(args.out) if args.out else None)


def cmd_replay(args: argparse.Namespace) -> int:
    product = Path(args.product) if args.product else None
    return host.replay(Path(args.run), product, Path(args.out) if args.out else None)


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

    p_agent = sub.add_parser("agent", help="run one sandboxed agent run locally (needs Docker)")
    p_agent.add_argument("mode", choices=[m.value for m in Mode])
    p_agent.add_argument("--product", default=".", help="local product checkout")
    p_agent.add_argument("--branch", help="feature/<ID> (default: current branch)")
    p_agent.add_argument("--phase", type=int, help="phase number (default: next open phase)")
    p_agent.add_argument("--feedback-file", help="failure report or review comments (fix, rework)")
    p_agent.add_argument("--max-turns", type=int, default=100)
    p_agent.add_argument("--model")
    p_agent.add_argument("--timeout", type=int, default=3600, help="wall clock seconds")
    p_agent.add_argument("--cpus", default=sandbox.Limits.cpus)
    p_agent.add_argument("--memory", default=sandbox.Limits.memory)
    p_agent.add_argument("--pids", type=int, default=sandbox.Limits.pids)
    p_agent.add_argument("--image", help="runner image (default: from factory.yaml runner)")
    p_agent.add_argument("--out", help=f"run folder (default: ${host.RUNS_DIR_ENV}/<run id>)")
    p_agent.add_argument("--no-apply", action="store_true", help="do not move the branch")
    p_agent.set_defaults(func=cmd_agent)

    p_replay = sub.add_parser("replay", help="re-run a recorded run from the same commit")
    p_replay.add_argument("run", help="run folder containing run.json")
    p_replay.add_argument("--product", help="local product checkout (default: as recorded)")
    p_replay.add_argument("--out", help="run folder for the replay")
    p_replay.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
