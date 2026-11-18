"""`factory` command-line interface."""

import argparse
import json
import os
import sys
from pathlib import Path

from factory import ci, dispatch, preview, review, screenshots, tasks
from factory.checks import git
from factory.checks.rules import (
    commit_size_violation,
    file_size_violations,
    protected_path_violations,
)
from factory.contract import CONTRACT_PATH, ContractError, load
from factory.init import CI_WORKFLOW, CONSTITUTION, InitError, init_product
from factory.runner import Mode, host, sandbox

PLACEHOLDER = "FACTORY:"


def _warnings(root: Path) -> list[str]:
    warnings = []
    contract_text = (root / CONTRACT_PATH).read_text()
    for line in contract_text.splitlines():
        if PLACEHOLDER in line and not line.lstrip().startswith("#"):
            warnings.append(f"{CONTRACT_PATH}: placeholder still set: {line.strip()}")
    workflow = root / CI_WORKFLOW
    if workflow.exists() and f"# {PLACEHOLDER}" in workflow.read_text():
        warnings.append(f"{CI_WORKFLOW}: set the factory repository (factory init --factory-repo)")
    for rel in (CONSTITUTION, Path("CLAUDE.md")):
        path = root / rel
        if path.exists() and f"<!-- {PLACEHOLDER}" in path.read_text():
            warnings.append(f"{rel}: product section not filled in yet")
    return warnings


def cmd_init(args: argparse.Namespace) -> int:
    try:
        report = init_product(
            Path(args.path),
            factory_repo=args.factory_repo or os.environ.get("FACTORY_REPO"),
        )
    except InitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for label, items in (("created", report.created), ("updated", report.updated)):
        for item in items:
            print(f"{label:8} {item}")
    for item in report.kept:
        print(f"kept     {item}")
    print("\nNext: open Claude Code in this directory and run /factory-setup")
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


def _branch(args: argparse.Namespace, root: Path) -> str:
    """--branch, else the branch GitHub Actions is building, else the checked-out branch."""
    env = os.environ
    return (
        args.branch
        or env.get("GITHUB_HEAD_REF")
        or env.get("GITHUB_REF_NAME")
        or (git.current_branch(root))
    )


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def cmd_next(args: argparse.Namespace) -> int:
    """Decide the next step after a factory workflow run and record it on the PR."""
    root = Path(args.root)
    env = os.environ
    branch = _branch(args, root)
    try:
        contract = load(root)
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    feature = tasks.feature_id(branch)
    spec = tasks.find_spec_dir(root, feature) if feature else None
    phases = tasks.parse((root / spec / "tasks.md").read_text()) if spec else []
    outcome = dispatch.outcome_from_files(
        args.step, args.phase, _path(args.run_json), args.checks, args.review,
        _path(args.ci_report), _path(args.review_report), args.reason or "",
    )  # fmt: skip
    gh = dispatch.GitHub(args.repo or env.get("GITHUB_REPOSITORY", ""))
    pr = gh.pr(branch)
    if pr is None:
        print(f"error: no pull request for {branch}", file=sys.stderr)
        return 1
    labels = [lbl["name"] for lbl in pr.get("labels", [])]
    decision = dispatch.decide(outcome, phases, dispatch.read_state(pr.get("body", "")),
                               contract, labels)  # fmt: skip
    run_url = args.run_url or "{}/{}/actions/runs/{}".format(
        env.get("GITHUB_SERVER_URL", "https://github.com"), env.get("GITHUB_REPOSITORY", ""),
        env.get("GITHUB_RUN_ID", ""),
    )  # fmt: skip
    if not args.dry_run:
        dispatch.record(gh, pr, outcome, decision, phases, run_url)
    if args.feedback_out:
        Path(args.feedback_out).write_text(decision.feedback)
    outputs = {"action": decision.action.value, "mode": decision.mode,
               "phase": str(decision.phase or ""), "reason": decision.reason}  # fmt: skip
    if out := env.get("GITHUB_OUTPUT"):
        with open(out, "a") as fh:
            fh.writelines(f"{k}={v.splitlines()[0] if v else ''}\n" for k, v in outputs.items())
    print(json.dumps(outputs))
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        contract = load(root)
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    steps = list(ci.STEPS) if "all" in args.steps else args.steps
    outcomes = ci.run(steps, root, contract, args.base, args.head)
    print()
    for o in outcomes:
        mark = "skip" if o.skipped else ("ok" if o.ok else "FAIL")
        print(f"{mark:5} {o.step:8} {o.detail}".rstrip())
    return 0 if all(o.ok for o in outcomes) else 1


def cmd_review(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        contract = load(root)
        feature = tasks.feature_id(_branch(args, root))
        spec = args.spec or (tasks.find_spec_dir(root, feature) if feature else None)
        shots = Path(args.screenshots) if args.screenshots else None
        result = review.review(
            root, contract, args.base, args.head, spec_dir=spec, screenshots=shots,
            max_turns=args.max_turns, model=args.model,
        )  # fmt: skip
    except (ContractError, review.ReviewError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = review.markdown(result)
    print(text)
    if args.json:
        Path(args.json).write_text(json.dumps(result.as_dict(), indent=2) + "\n")
    if args.markdown:
        Path(args.markdown).write_text(text)
    return 0 if result.passed else 1


def cmd_screenshots(args: argparse.Namespace) -> int:
    auth = os.environ.get(preview.AUTH_ENV) or None
    paths = args.path
    if not paths:
        try:
            contract = load(Path(args.root))
            paths = contract.preview.screenshots if contract.preview else ["/"]
        except ContractError:
            paths = ["/"]
    try:
        if args.commit:
            preview.wait_for_commit(args.url, args.commit, auth, args.timeout)
        files = screenshots.take(args.url, paths, Path(args.out), auth)
    except (preview.PreviewError, screenshots.ScreenshotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for file in files:
        print(file)
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    root = Path(args.product)
    try:
        if args.action == "status":
            print(json.dumps(preview.status(), indent=2))
            return 0
        branch = _branch(args, root)
        if args.action == "url":
            print(preview.preview_url(branch, args.domain) or "")
            return 0
        if args.action == "down":
            removed = preview.down(branch)
            print(f"removed {preview.project(preview.preview_id(branch))}" if removed else "none")
            return 0
        state = preview.up(root, args.ref, branch, domain=args.domain, timeout=args.timeout)
    except preview.PreviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"preview {state.id} at {state.commit[:12]}: {state.url or 'local only (no domain)'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description="AI software factory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="make a repository a factory product")
    p_init.add_argument("path", nargs="?", default=".")

    p_init.add_argument(
        "--factory-repo", help="owner/repo of the software factory, for the CI workflow"
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

    p_ci = sub.add_parser("ci", help="run CI steps: product commands, factory checks, scanners")
    p_ci.add_argument("steps", nargs="+", choices=[*ci.STEPS, "all"])
    p_ci.add_argument("--root", default=".")
    p_ci.add_argument("--base", help="check the commits in base..head (push before, PR base)")
    p_ci.add_argument("--head", default="HEAD")
    p_ci.set_defaults(func=cmd_ci)

    p_next = sub.add_parser("next", help="dispatcher: decide and record the next step (CI)")
    p_next.add_argument("--step", required=True, choices=[s.value for s in dispatch.Step])
    p_next.add_argument("--phase", type=int, help="phase the run worked on")
    p_next.add_argument("--run-json", help="the agent run's run.json")
    p_next.add_argument("--checks", default="skipped", help="checks job result")
    p_next.add_argument("--review", default="skipped", help="review job result")
    p_next.add_argument("--ci-report", help="checks output, passed to a fix run")
    p_next.add_argument("--review-report", help="review Markdown, passed to a fix or rework run")
    p_next.add_argument("--reason", help="why (replan)")
    p_next.add_argument("--branch", help="feature branch (default: from CI or git)")
    p_next.add_argument("--root", default=".")
    p_next.add_argument("--repo", help="owner/repo (default: $GITHUB_REPOSITORY)")
    p_next.add_argument("--run-url", help="link for the PR comment (default: this run)")
    p_next.add_argument("--feedback-out", help="write the next run's feedback here")
    p_next.add_argument("--dry-run", action="store_true", help="decide only; change nothing")
    p_next.set_defaults(func=cmd_next)

    p_rev = sub.add_parser("review", help="read-only agent review against the constitution")
    p_rev.add_argument("--root", default=".")
    p_rev.add_argument("--base", required=True)
    p_rev.add_argument("--head", default="HEAD")
    p_rev.add_argument("--branch", help="feature branch (default: from CI or git)")
    p_rev.add_argument("--spec", help="spec folder (default: from specs/*/source.yaml)")
    p_rev.add_argument("--screenshots", help="folder of preview screenshots to review")
    p_rev.add_argument("--json", help="write the verdict as JSON")
    p_rev.add_argument("--markdown", help="write the review as Markdown (PR comment)")
    p_rev.add_argument("--max-turns", type=int, default=40)
    p_rev.add_argument("--model")
    p_rev.set_defaults(func=cmd_review)

    p_shot = sub.add_parser("screenshots", help="Playwright screenshots of a preview")
    p_shot.add_argument("url")
    p_shot.add_argument("--out", required=True)
    p_shot.add_argument("--path", action="append", help="default: preview.screenshots")
    p_shot.add_argument("--root", default=".")
    p_shot.add_argument("--commit", help="wait until the preview serves this commit")
    p_shot.add_argument("--timeout", type=int, default=600)
    p_shot.set_defaults(func=cmd_screenshots)

    p_prev = sub.add_parser("preview", help="per-feature preview from the product's compose file")
    p_prev.add_argument("action", choices=["up", "down", "status", "url"])
    p_prev.add_argument("--product", default=".", help="local product checkout")
    p_prev.add_argument("--ref", default="HEAD", help="commit to deploy (up)")
    p_prev.add_argument("--branch", help="feature branch (default: from CI or git)")
    p_prev.add_argument("--domain", help=f"preview domain (default: ${preview.DOMAIN_ENV})")
    p_prev.add_argument("--timeout", type=int, default=300)
    p_prev.set_defaults(func=cmd_preview)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
