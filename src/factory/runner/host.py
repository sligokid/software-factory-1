"""Host side of a run: `factory agent` and `factory replay`.

The product branch goes into the container as a git bundle on stdin and the resulting commit
comes back as a bundle in the transcript's `factory_result` record, so no host path is mounted.
Each run leaves a folder with run.json, transcript.jsonl, runner.log and egress.log.
"""

import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Any

import yaml

from factory.contract import CONTRACT_PATH, ContractError, parse
from factory.runner import INPUT_REF, Mode, image, sandbox

RUNS_DIR_ENV = "FACTORY_RUNS_DIR"
EXIT_TIMEOUT = 124


@dataclass
class RunRequest:
    product: Path
    branch: str
    mode: Mode
    phase: int | None = None
    feedback: str = ""
    max_turns: int = 100
    model: str | None = None
    timeout: int = 3600
    limits: sandbox.Limits = field(default_factory=sandbox.Limits)
    image: str | None = None
    rev: str | None = None  # start commit; default: the branch head
    apply: bool = True  # move the local branch to the result commit


def runs_dir() -> Path:
    return Path(os.environ.get(RUNS_DIR_ENV, Path.home() / ".factory" / "runs"))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def run_id(branch: str, mode: Mode, phase: int | None) -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", branch.removeprefix("feature/").lower()).strip("-")
    return f"{slug}-{mode.value}{phase or ''}-{stamp}"


def _docker(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def _tee(stream: IO[bytes], path: Path) -> None:
    with path.open("wb") as out:
        for line in stream:
            out.write(line)
            sys.stderr.buffer.write(line)
            sys.stderr.buffer.flush()


def _read_output(stream: IO[bytes], run_dir: Path) -> dict[str, Any]:
    """Save the transcript; return the factory_result record (its bundle saved to a file)."""
    result: dict[str, Any] = {}
    with (run_dir / "transcript.jsonl").open("wb") as transcript:
        for line in stream:
            if line.startswith(b'{"type": "factory_result"'):
                result = json.loads(line)
                if bundle := result.pop("bundle", None):
                    (run_dir / "result.bundle").write_bytes(base64.b64decode(bundle))
                line = json.dumps(result).encode() + b"\n"
            transcript.write(line)
    return result


def _usage(run_dir: Path) -> dict[str, Any]:
    """Turns, cost and tokens from Claude's final `result` message."""
    usage: dict[str, Any] = {}
    for line in (run_dir / "transcript.jsonl").read_text(errors="replace").splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "result":
            keys = ("subtype", "num_turns", "duration_ms", "total_cost_usd", "usage")
            usage = {k: msg.get(k) for k in keys}
    return usage


def _apply(req: RunRequest, run_dir: Path, rev: str, ref: str) -> str:
    _git(
        req.product, "fetch", "-q", str(run_dir / "result.bundle"), f"refs/heads/{req.branch}:{ref}"
    )
    commit = _git(req.product, "rev-parse", ref)
    if not req.apply:
        return f"result kept at {ref}"
    current = _git(req.product, "branch", "--show-current")
    if current != req.branch:
        _git(req.product, "update-ref", f"refs/heads/{req.branch}", commit, rev)
    elif (
        _git(req.product, "status", "--porcelain") or _git(req.product, "rev-parse", "HEAD") != rev
    ):
        return f"{req.branch} is checked out and changed; result kept at {ref}"
    else:
        _git(req.product, "reset", "-q", "--keep", commit)
    return f"{req.branch} -> {commit[:12]}"


def _start_sandbox(name: str, img: str, allow: list[str]) -> None:
    _docker(*sandbox.network_create(name)[1:], check=True)
    _docker(*sandbox.proxy_run(f"{name}-egress", img, allow)[1:], check=True)
    _docker(*sandbox.proxy_connect(name, f"{name}-egress")[1:], check=True)
    deadline = time.monotonic() + 30
    while "egress proxy on" not in _docker("logs", f"{name}-egress").stderr:
        if time.monotonic() > deadline:
            raise subprocess.CalledProcessError(1, ["docker", "egress proxy"], "", "not ready")
        time.sleep(0.2)


def _stop_sandbox(name: str, run_dir: Path) -> None:
    logs = _docker("logs", f"{name}-egress")
    (run_dir / "egress.log").write_text(logs.stdout + logs.stderr)
    _docker("rm", "-f", f"{name}-egress")
    _docker("network", "rm", name)


def agent(req: RunRequest, run_dir: Path | None = None) -> int:
    product = req.product.resolve()
    req.product = product
    rev = req.rev or _git(product, "rev-parse", f"refs/heads/{req.branch}")
    try:
        contract = parse(yaml.safe_load(_git(product, "show", f"{rev}:{CONTRACT_PATH.as_posix()}")))
    except (ContractError, subprocess.CalledProcessError, yaml.YAMLError) as exc:
        print(f"error: cannot read the contract at {rev}: {exc}", file=sys.stderr)
        return 1
    rid = run_id(req.branch, req.mode, req.phase)
    run_dir = run_dir or runs_dir() / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    img = req.image or image(contract.runner)
    (run_dir / "feedback.txt").write_text(req.feedback)

    _git(product, "update-ref", INPUT_REF, rev)
    try:
        _git(product, "bundle", "create", "-q", str(run_dir / "input.bundle"), INPUT_REF)
    finally:
        _git(product, "update-ref", "-d", INPUT_REF)

    name = f"factory-{rid}"
    env = {"FACTORY_MODE": req.mode.value, "FACTORY_BRANCH": req.branch, "FACTORY_SOURCE": "stdin"}
    env |= {"FACTORY_MAX_TURNS": str(req.max_turns), "FACTORY_FEEDBACK": req.feedback}
    if req.phase:
        env["FACTORY_PHASE"] = str(req.phase)
    if req.model:
        env["FACTORY_MODEL"] = req.model
    started = dt.datetime.now(dt.UTC)
    timed_out = threading.Event()
    try:
        _start_sandbox(name, img, contract.allowed_hosts)
        cmd = sandbox.agent_run(name, img, name, env, req.limits)
        with (run_dir / "input.bundle").open("rb") as stdin:
            proc = subprocess.Popen(
                cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        assert proc.stdout is not None and proc.stderr is not None
        tee = threading.Thread(target=_tee, args=(proc.stderr, run_dir / "runner.log"))
        tee.start()

        def kill() -> None:
            timed_out.set()
            _docker("kill", name)

        timer = threading.Timer(req.timeout, kill)
        timer.start()
        result = _read_output(proc.stdout, run_dir)
        code = proc.wait()
        timer.cancel()
        tee.join()
    except subprocess.CalledProcessError as exc:
        print(f"error: {' '.join(exc.cmd[:3])}...: {exc.stderr}", file=sys.stderr)
        return 1
    finally:
        _stop_sandbox(name, run_dir)

    if timed_out.is_set():
        code, result = EXIT_TIMEOUT, {"status": "failed", "reason": f"timeout after {req.timeout}s"}
    applied = None
    if result.get("status") == "ok" and (run_dir / "result.bundle").exists():
        applied = _apply(req, run_dir, rev, f"refs/factory/runs/{rid}")
    record = {
        "id": rid,
        "image": img,
        "rev": rev,
        "request": {**asdict(req), "product": str(product), "feedback": None},
        "started": started.isoformat(),
        "finished": dt.datetime.now(dt.UTC).isoformat(),
        "exit_code": code,
        "result": result,
        "usage": _usage(run_dir),
        "applied": applied,
    }
    (run_dir / "run.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    status = result.get("status", "failed")
    print(f"{status}: {result.get('reason') or applied or ''} (run: {run_dir})".rstrip())
    return code if code else (0 if status == "ok" else 1)


def replay(run_dir: Path, product: Path | None = None, out: Path | None = None) -> int:
    """Re-run a recorded run from the same commit, with the same mode, phase, feedback and image.

    The result is kept under refs/factory/runs/ and never moves the branch.
    """
    record = json.loads((run_dir / "run.json").read_text())
    r = record["request"]
    req = RunRequest(
        product=product or Path(r["product"]),
        branch=r["branch"],
        mode=Mode(r["mode"]),
        phase=r["phase"],
        feedback=(run_dir / "feedback.txt").read_text(),
        max_turns=r["max_turns"],
        model=r["model"],
        timeout=r["timeout"],
        limits=sandbox.Limits(**r["limits"]),
        image=record["image"],
        rev=record["rev"],
        apply=False,
    )
    return agent(req, out)
