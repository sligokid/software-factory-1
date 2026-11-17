"""`factory ci`: the checks every product's CI runs, the same locally and in GitHub Actions.

Product steps run the contract's commands. Generic steps run the factory checks and three
language-agnostic scanners installed in the runner images: gitleaks (secrets), semgrep (SAST)
and osv-scanner (dependencies).
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from factory.checks import git
from factory.checks.rules import (
    commit_size_violation,
    file_size_violations,
    protected_path_violations,
)
from factory.contract import Contract
from factory.runner import AGENT_GIT_NAME

PRODUCT_STEPS = ("setup", "verify", "checks")
GENERIC_STEPS = ("factory", "secrets", "sast", "deps")
STEPS = PRODUCT_STEPS + GENERIC_STEPS
SEMGREP_CONFIG_ENV = "FACTORY_SEMGREP_CONFIG"
DEFAULT_SEMGREP_CONFIG = "p/default"
OSV_NO_PACKAGES = 128  # osv-scanner: no lockfile or manifest found
NULL_SHA = "0" * 40


@dataclass(frozen=True)
class Outcome:
    step: str
    ok: bool
    detail: str = ""
    skipped: bool = False


def _shell(command: str, root: Path) -> int:
    print(f"$ {command}", flush=True)
    return subprocess.run(command, shell=True, cwd=root, check=False).returncode  # noqa: S602


def _tool(root: Path, step: str, cmd: list[str]) -> int | Outcome:
    if shutil.which(cmd[0]) is None:
        return Outcome(step, False, f"{cmd[0]} not installed: run in the runner image")
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=root, check=False).returncode


def product_step(step: str, root: Path, contract: Contract) -> Outcome:
    command = getattr(contract, step)
    if not command:
        return Outcome(step, True, "not defined in factory.yaml", skipped=True)
    code = _shell(command, root)
    return Outcome(step, code == 0, f"exit {code}" if code else "")


def factory_step(root: Path, contract: Contract, base: str | None, head: str) -> Outcome:
    """File size limits; per commit in base..head: commit size, and protected paths for commits
    authored by the factory agent."""
    problems = [f"size limit: {v}" for v in file_size_violations(root, contract)]
    for commit in git.commits(root, base, head) if base else []:
        changes = git.changes(root, f"{commit.sha}^", commit.sha)
        label = f"{commit.sha[:10]} {commit.subject}"
        if (violation := commit_size_violation(changes, contract)) is not None:
            problems.append(f"{label}: commit size: {violation}")
        if commit.author == AGENT_GIT_NAME:
            for path in protected_path_violations(changes, contract):
                problems.append(f"{label}: agent changed protected path {path}")
    for problem in problems:
        print(problem)
    return Outcome("factory", not problems, f"{len(problems)} problem(s)" if problems else "")


def secrets_step(root: Path, base: str | None, head: str) -> Outcome:
    cmd = ["gitleaks", "git", "--no-banner", "--redact", "--exit-code", "1"]
    if base:
        cmd += ["--log-opts", f"{base}..{head}"]
    code = _tool(root, "secrets", [*cmd, "."])
    if isinstance(code, Outcome):
        return code
    return Outcome("secrets", code == 0, "secrets found" if code == 1 else f"exit {code}")


def sast_step(root: Path, base: str | None) -> Outcome:
    configs = os.environ.get(SEMGREP_CONFIG_ENV, DEFAULT_SEMGREP_CONFIG).split(",")
    if (root / ".semgrep.yml").is_file():
        configs.append(".semgrep.yml")  # product-specific rules
    cmd = ["semgrep", "scan", "--error", "--metrics", "off", "--disable-version-check", "--quiet"]
    for config in configs:
        cmd += ["--config", config]
    if base:
        cmd += ["--baseline-commit", base]  # only findings introduced since base
    code = _tool(root, "sast", cmd)
    if isinstance(code, Outcome):
        return code
    return Outcome("sast", code == 0, "findings" if code == 1 else f"exit {code}" if code else "")


def deps_step(root: Path) -> Outcome:
    code = _tool(root, "deps", ["osv-scanner", "scan", "source", "--recursive", "."])
    if isinstance(code, Outcome):
        return code
    if code == OSV_NO_PACKAGES:
        return Outcome("deps", True, "no lockfiles or manifests found", skipped=True)
    return Outcome("deps", code == 0, "vulnerable dependencies" if code == 1 else f"exit {code}")


def resolve_base(root: Path, base: str | None) -> str | None:
    """None, a null SHA (new branch push) or an unknown ref means: no commit range."""
    if not base or base == NULL_SHA:
        return None
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        print(f"warning: base {base} not found; checking without a commit range", file=sys.stderr)
        return None
    return probe.stdout.strip()


def run(
    steps: list[str], root: Path, contract: Contract, base: str | None, head: str = "HEAD"
) -> list[Outcome]:
    base = resolve_base(root, base)
    runners: dict[str, Callable[[], Outcome]] = {
        "factory": lambda: factory_step(root, contract, base, head),
        "secrets": lambda: secrets_step(root, base, head),
        "sast": lambda: sast_step(root, base),
        "deps": lambda: deps_step(root),
    }
    outcomes = []
    for step in steps:
        print(f"::group::factory ci {step}" if os.environ.get("GITHUB_ACTIONS") else f"== {step}")
        outcome = runners[step]() if step in runners else product_step(step, root, contract)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::endgroup::")
        outcomes.append(outcome)
    return outcomes
