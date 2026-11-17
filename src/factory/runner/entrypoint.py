"""`factory-runner`: the runner container's entrypoint.

Refuses API keys, gets the product repo (git bundle on stdin, or clone from GitHub), runs the
contract's `setup`, runs headless Claude Code in one mode, then checks and delivers the result
as exactly one commit. stdout is the run transcript (Claude's stream-json) ending with one
`factory_result` record; logs go to stderr.
"""

import base64
import json
import os
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from factory import tasks
from factory.checks import git
from factory.checks.rules import (
    commit_size_violation,
    file_size_violations,
    protected_path_violations,
)
from factory.contract import Contract, ContractError, load
from factory.runner import INPUT_REF, Mode, prompts
from factory.runner.tools import claude_command

EXIT_OK, EXIT_REFUSED, EXIT_FAILED = 0, 2, 3
REFUSED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
SECRET_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "FACTORY_FEEDBACK")
CREDENTIAL_HELPER = (
    "credential.helper=!f() { echo username=x-access-token; "
    'echo "password=$FACTORY_PUSH_TOKEN"; }; f'
)


class RunError(Exception):
    def __init__(self, reason: str, exit_code: int = EXIT_FAILED, log: str = "") -> None:
        super().__init__(reason)
        self.reason, self.exit_code, self.log = reason, exit_code, log


@dataclass
class Config:
    mode: Mode
    branch: str
    source: str  # stdin | git
    phase: int | None = None
    spec: str | None = None
    repo_url: str | None = None
    feedback: str = ""
    max_turns: int = 100
    model: str | None = None
    token: str | None = field(default=None, repr=False)

    @property
    def feature_id(self) -> str:
        return self.branch.removeprefix("feature/")

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Config":
        try:
            mode = Mode(env.get("FACTORY_MODE", ""))
        except ValueError as exc:
            raise RunError(
                f"FACTORY_MODE must be one of {[m.value for m in Mode]}", EXIT_REFUSED
            ) from exc
        branch = env.get("FACTORY_BRANCH", "")
        if not branch.startswith("feature/") or branch == "feature/":
            raise RunError("FACTORY_BRANCH must be feature/<ID>", EXIT_REFUSED)
        source = env.get("FACTORY_SOURCE", "stdin")
        if source not in ("stdin", "git") or (source == "git" and not env.get("FACTORY_REPO_URL")):
            raise RunError(
                "FACTORY_SOURCE must be stdin, or git with FACTORY_REPO_URL", EXIT_REFUSED
            )
        phase = env.get("FACTORY_PHASE")
        return cls(
            mode=mode,
            branch=branch,
            source=source,
            phase=int(phase) if phase else None,
            spec=env.get("FACTORY_SPEC") or None,
            repo_url=env.get("FACTORY_REPO_URL"),
            feedback=env.get("FACTORY_FEEDBACK", ""),
            max_turns=int(env.get("FACTORY_MAX_TURNS", "100")),
            model=env.get("FACTORY_MODEL") or None,
            token=env.get("GH_TOKEN") or env.get("GITHUB_TOKEN"),
        )


def credentials_error(env: dict[str, str]) -> str | None:
    for name in REFUSED_ENV:
        if name in env:
            return f"{name} is set: the factory only runs on a Claude subscription token"
    if not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "CLAUDE_CODE_OAUTH_TOKEN is required"
    return None


def log(message: str) -> None:
    print(f"[factory-runner] {message}", file=sys.stderr, flush=True)


def clean_env(*drop: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in SECRET_ENV + drop}


def sh(command: str, cwd: Path) -> tuple[int, str]:
    """Run a product command, streaming its output to stderr; return exit code and output tail."""
    log(f"$ {command}")
    tail: deque[str] = deque(maxlen=60)
    proc = subprocess.Popen(  # noqa: S602 - product commands are shell command lines
        command,
        shell=True,
        cwd=cwd,
        env=clean_env("CLAUDE_CODE_OAUTH_TOKEN"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stderr.write(line)
        tail.append(line)
    return proc.wait(), "".join(tail)


def gitc(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env or clean_env(),
    )
    return out.stdout.strip()


def prepare_repo(cfg: Config, repo: Path) -> None:
    if cfg.source == "stdin":
        bundle = repo.parent / "input.bundle"
        bundle.write_bytes(sys.stdin.buffer.read())
        repo.mkdir(parents=True)
        gitc(repo, "init", "-q")
        gitc(repo, "fetch", "-q", str(bundle), f"{INPUT_REF}:{INPUT_REF}")
        gitc(repo, "checkout", "-q", "-b", cfg.branch, INPUT_REF)
    else:
        assert cfg.repo_url is not None
        env = {**clean_env(), "FACTORY_PUSH_TOKEN": cfg.token or ""}
        subprocess.run(
            ["git", "-c", CREDENTIAL_HELPER, "clone", "-q", "--branch", cfg.branch,
             cfg.repo_url, str(repo)],
            check=True, env=env,
        )  # fmt: skip
    gitc(repo, "config", "user.name", os.environ.get("FACTORY_GIT_NAME", "factory-agent"))
    gitc(repo, "config", "user.email", os.environ.get("FACTORY_GIT_EMAIL", "factory@invalid"))


def find_spec_dir(repo: Path, feature_id: str) -> str:
    for source in sorted(repo.glob("specs/*/source.yaml")):
        data = yaml.safe_load(source.read_text()) or {}
        if str(data.get("id", "")) == feature_id:
            return source.parent.relative_to(repo).as_posix()
    raise RunError(f"no specs/*/source.yaml with id {feature_id}")


def read_phases(repo: Path, spec_dir: str, rev: str | None = None) -> list[tasks.Phase]:
    rel = f"{spec_dir}/tasks.md"
    text = gitc(repo, "show", f"{rev}:{rel}") if rev else (repo / rel).read_text()
    return tasks.parse(text)


def select_phase(cfg: Config, phases: list[tasks.Phase]) -> tasks.Phase | None:
    if cfg.mode is Mode.IMPLEMENT:
        phase = tasks.find(phases, cfg.phase) if cfg.phase else tasks.next_open(phases)
        if phase is None or not phase.tasks or phase.done:
            raise RunError(f"no open phase to implement (requested: {cfg.phase or 'next'})")
        return phase
    if cfg.mode is Mode.FIX:
        done = [p for p in phases if p.done]
        phase = tasks.find(phases, cfg.phase) if cfg.phase else (done[-1] if done else None)
        if phase is None:
            raise RunError("no implemented phase to fix")
        return phase
    return None


def check_scope(
    cfg: Config, repo: Path, spec_dir: str, base: str, phase: tasks.Phase | None
) -> None:
    """Mode-specific checks on the staged result."""
    changed = gitc(repo, "diff", "--cached", "--name-only", base).splitlines()
    if cfg.mode is Mode.CONVERGE and set(changed) - {f"{spec_dir}/tasks.md"}:
        raise RunError(f"converge may only change {spec_dir}/tasks.md, changed: {changed}")
    if cfg.mode is Mode.IMPLEMENT and phase is not None:
        before = {t.id for p in read_phases(repo, spec_dir, base) for t in p.tasks if t.done}
        after = read_phases(repo, spec_dir)
        current = tasks.find(after, phase.number)
        if current is None or not current.done:
            raise RunError(f"{phase.name}: not every task is checked in tasks.md")
        extra = [
            t.id for p in after if p.number != phase.number
            for t in p.tasks if t.done and t.id not in before
        ]  # fmt: skip
        if extra:
            raise RunError(f"tasks outside {phase.name} were checked: {extra}")


def quality_gates(contract: Contract, repo: Path, base: str) -> None:
    for name, command in (("verify", contract.verify), ("checks", contract.checks)):
        if command:
            code, tail = sh(command, repo)
            if code != 0:
                raise RunError(f"{name} failed (exit {code})", log=tail)
    changes = git.changes(repo, base)
    problems = [f"size limit: {v}" for v in file_size_violations(repo, contract)]
    if (violation := commit_size_violation(changes, contract)) is not None:
        problems.append(f"commit size: {violation}")
    problems += [
        f"protected path changed: {p}" for p in protected_path_violations(changes, contract)
    ]
    if problems:
        raise RunError("factory checks failed", log="\n".join(problems))


def deliver(cfg: Config, repo: Path, base: str, original_head: str) -> dict[str, Any]:
    if cfg.source == "stdin":
        bundle = repo.parent / "output.bundle"
        gitc(repo, "bundle", "create", "-q", str(bundle), f"refs/heads/{cfg.branch}", f"^{base}")
        return {"bundle": base64.b64encode(bundle.read_bytes()).decode()}
    env = {**clean_env(), "FACTORY_PUSH_TOKEN": cfg.token or ""}
    lease = f"--force-with-lease=refs/heads/{cfg.branch}:{original_head}"
    gitc(repo, "-c", CREDENTIAL_HELPER, "push", "-q", lease, "origin",
         f"HEAD:refs/heads/{cfg.branch}", env=env)  # fmt: skip
    return {"pushed": True}


def commit_message(cfg: Config, repo: Path, phase: tasks.Phase | None) -> str:
    if cfg.mode is Mode.FIX:
        return gitc(repo, "log", "-1", "--format=%B")
    label = phase.name if phase else cfg.mode.value
    return f"{cfg.feature_id}: {label}"


def run(cfg: Config, repo: Path) -> dict[str, Any]:
    prepare_repo(cfg, repo)
    try:
        contract = load(repo)
    except ContractError as exc:
        raise RunError(str(exc)) from exc
    spec_dir = cfg.spec or find_spec_dir(repo, cfg.feature_id)
    phase = select_phase(cfg, read_phases(repo, spec_dir))
    original_head = gitc(repo, "rev-parse", "HEAD")
    base = gitc(repo, "rev-parse", "HEAD~1") if cfg.mode is Mode.FIX else original_head
    message = commit_message(cfg, repo, phase)
    log(f"mode={cfg.mode} branch={cfg.branch} spec={spec_dir} phase={phase and phase.name}")

    if contract.setup:
        code, tail = sh(contract.setup, repo)
        if code != 0:
            raise RunError(f"setup failed (exit {code})", log=tail)

    prompt = prompts.build(cfg.mode, contract, spec_dir, phase=phase, feedback=cfg.feedback)
    cmd = claude_command(prompt, contract, max_turns=cfg.max_turns, model=cfg.model)
    sys.stdout.flush()
    code = subprocess.run(cmd, cwd=repo, env=clean_env(), check=False).returncode
    if code != 0:
        raise RunError(f"claude exited {code}")

    gitc(repo, "add", "-A")
    result: dict[str, Any] = {"spec": spec_dir, "phase": phase and phase.number, "base": base}
    if (
        subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet", base]).returncode
        == 0
    ):
        if cfg.mode is Mode.CONVERGE:
            return {**result, "converged": True}
        raise RunError("the agent made no changes")
    check_scope(cfg, repo, spec_dir, base, phase)
    gitc(repo, "reset", "-q", "--soft", base)
    gitc(repo, "commit", "-q", "--no-verify", "-m", message)
    quality_gates(contract, repo, base)
    commit = gitc(repo, "rev-parse", "HEAD")
    log(f"commit {commit[:12]} {message.splitlines()[0]}")
    return {
        **result,
        "commit": commit,
        "converged": False,
        **deliver(cfg, repo, base, original_head),
    }


def emit(record: dict[str, Any]) -> None:
    print(json.dumps({"type": "factory_result", **record}), flush=True)


def main() -> int:
    env = dict(os.environ)
    if error := credentials_error(env):
        log(f"refused: {error}")
        emit({"status": "refused", "reason": error})
        return EXIT_REFUSED
    workspace = Path(env.get("FACTORY_WORKSPACE", "/workspace"))
    try:
        cfg = Config.from_env(env)
        record = run(cfg, workspace / "repo")
    except RunError as exc:
        log(f"failed: {exc.reason}")
        status = "refused" if exc.exit_code == EXIT_REFUSED else "failed"
        emit({"status": status, "reason": exc.reason, "log": exc.log})
        return exc.exit_code
    except subprocess.CalledProcessError as exc:
        log(f"failed: {exc}")
        emit({"status": "failed", "reason": str(exc), "log": exc.stderr or ""})
        return EXIT_FAILED
    emit({"status": "ok", "mode": cfg.mode.value, **record})
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
