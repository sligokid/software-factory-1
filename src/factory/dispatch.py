"""`factory next`: the dispatcher's decision at the end of each factory workflow run (stage 4).

Every run of the product workflow does one step (an agent run, then checks and review on its
commit, or the final whole-PR review). `factory next` reads what happened, the phases in
tasks.md and the counters kept in a marker in the PR body, decides the next step, records it on
the PR (marker, phase table, labels, comment) and tells the workflow what to dispatch. The
factory keeps no other state.
"""

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from factory import tasks
from factory.contract import Contract

STATE_RE = re.compile(r"<!-- factory:state (\{.*?\}) -->")
PHASES_START, PHASES_END = "<!-- factory:phases -->", "<!-- /factory:phases -->"
FEEDBACK_LIMIT = 20_000  # characters of CI or review output passed to the next run

READY, WORKING, AWAITING = "factory:ready", "factory:working", "factory:awaiting-review"
FAILED, REPLAN, TAKEOVER = "factory:failed", "factory:needs-replan", "human-takeover"
STATUS_LABELS = (READY, WORKING, AWAITING, FAILED, REPLAN)


class Step(StrEnum):
    """What a factory workflow run did (the agent modes plus the dispatcher's own steps)."""

    IMPLEMENT = "implement"
    FIX = "fix"
    CONVERGE = "converge"
    REWORK = "rework"
    FINAL = "final"  # whole-PR review before the PR is marked ready
    REPLAN = "replan"  # `@agent replan` comment, or the PR closed without merging


class Action(StrEnum):
    DISPATCH = "dispatch"  # start another run with mode and phase
    READY = "ready"  # mark the PR ready for review
    FAILED = "failed"  # stop: a limit was hit or the run cannot be retried
    REPLAN = "replan"  # stop: the developer revises the remaining phases
    PAUSED = "paused"  # stop: a human took over


@dataclass
class State:
    """Counters kept in the PR body between runs."""

    attempts: int = 0  # failed attempts at the current step; reset when a step passes
    converge: int = 0  # converge rounds that added phases
    rework: int = 0  # rework runs
    runs: int = 0  # workflow runs so far


@dataclass
class Outcome:
    """What the run that just finished did."""

    step: Step
    phase: int | None = None
    agent: str = "none"  # ok | failed | timeout | refused | none (no agent run)
    reason: str = ""
    log: str = ""
    converged: bool = False
    commit: str = ""
    checks: str = "skipped"  # GitHub job results: success | failure | cancelled | skipped
    review: str = "skipped"
    ci_report: str = ""
    review_report: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    action: Action
    state: State
    mode: str = ""
    phase: int | None = None
    feedback: str = ""
    reason: str = ""


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= FEEDBACK_LIMIT else "...\n" + text[-FEEDBACK_LIMIT:]


def _retry_or_fail(
    s: State, limit: int, mode: str, phase: int | None, feedback: str, why: str
) -> Decision:
    if s.attempts >= limit:
        return Decision(Action.FAILED, s, reason=f"{why}; {limit} fix attempt(s) used")
    s.attempts += 1
    return Decision(Action.DISPATCH, s, mode, phase, _clip(feedback), f"{why}: retry")


def decide(
    o: Outcome, phases: list[tasks.Phase], state: State, contract: Contract, labels: Sequence[str]
) -> Decision:
    s = State(**asdict(state))
    s.runs += 1
    if o.step is Step.REPLAN:
        return Decision(Action.REPLAN, s, reason=o.reason or "replan requested")
    if TAKEOVER in labels:
        return Decision(Action.PAUSED, s, reason=f"`{TAKEOVER}` label is set")

    if o.step is Step.FINAL:
        if o.review in ("success", "skipped"):
            return Decision(Action.READY, s, reason="whole-PR review passed")
        if s.rework >= contract.rework_rounds:
            return Decision(Action.FAILED, s, reason="whole-PR review failed; rework limit hit")
        s.rework += 1
        return Decision(
            Action.DISPATCH, s, Step.REWORK, None, _clip(o.review_report),
            "whole-PR review found blocking issues",
        )  # fmt: skip

    if o.agent in ("timeout", "refused", "none"):
        return Decision(Action.FAILED, s, reason=o.reason or f"agent run {o.agent}")
    if o.agent != "ok":
        if o.step is Step.CONVERGE:
            return Decision(Action.FAILED, s, reason=f"converge failed: {o.reason}")
        feedback = f"{o.reason}\n\n{o.log}"
        why = f"{o.step} run failed: {o.reason}"
        return _retry_or_fail(s, contract.fixes, o.step, o.phase, feedback, why)

    if o.step is Step.CONVERGE:
        if o.converged:
            s.attempts = 0
            return Decision(Action.DISPATCH, s, Step.FINAL, reason="converged")
        s.converge += 1
        if s.converge > contract.converge_rounds:
            return Decision(Action.FAILED, s, reason="converge keeps adding phases")
    elif o.checks not in ("success", "skipped") or o.review not in ("success", "skipped"):
        failed = [n for n, r in (("checks", o.checks), ("review", o.review)) if r == "failure"]
        report = "\n\n".join(r for r in (o.ci_report, o.review_report) if r.strip())
        why = f"{' and '.join(failed) or 'CI'} failed on {o.commit[:10] or 'the commit'}"
        return _retry_or_fail(s, contract.fixes, Step.FIX, o.phase, report, why)

    s.attempts = 0
    nxt = tasks.next_open(phases)
    if nxt is not None:
        return Decision(Action.DISPATCH, s, Step.IMPLEMENT, nxt.number, reason="next phase")
    return Decision(Action.DISPATCH, s, Step.CONVERGE, reason="all phases done")


# --- PR body ---------------------------------------------------------------------------------


def read_state(body: str) -> State:
    m = STATE_RE.search(body or "")
    if not m:
        return State()
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return State()
    return State(**{k: int(v) for k, v in data.items() if k in State.__dataclass_fields__})


def phase_table(phases: list[tasks.Phase]) -> str:
    rows = ["| Phase | Tasks | Done |", "|-------|-------|------|"]
    for p in phases:
        ids = f"{p.tasks[0].id}-{p.tasks[-1].id}" if p.tasks else "-"
        done = sum(t.done for t in p.tasks)
        rows.append(f"| {p.name} | {ids} | {'✅' if p.done else f'{done}/{len(p.tasks)}'} |")
    return "\n".join(rows)


def update_body(body: str, state: State, phases: list[tasks.Phase]) -> str:
    body = body or ""
    marker = f"<!-- factory:state {json.dumps(asdict(state), separators=(',', ':'))} -->"
    body = STATE_RE.sub(lambda _: marker, body) if STATE_RE.search(body) else f"{body}\n{marker}"
    table = f"{PHASES_START}\n{phase_table(phases)}\n{PHASES_END}"
    pattern = re.compile(re.escape(PHASES_START) + r".*?" + re.escape(PHASES_END), re.S)
    if pattern.search(body):
        return pattern.sub(lambda _: table, body)
    return f"{body}\n\n### Factory progress\n{table}\n"


def comment(o: Outcome, d: Decision, run_url: str) -> str:
    what = f"{o.step}" + (f" phase {o.phase}" if o.phase else "")
    lines = [f"### 🏭 Factory: {what}", ""]
    if o.agent != "none":
        u = o.usage
        cost = u.get("total_cost_usd")
        secs = (u.get("duration_ms") or 0) / 1000
        lines.append(
            f"- agent: **{o.agent}**" + (f" ({o.reason})" if o.reason and o.agent != "ok" else "")
            + (f" · commit `{o.commit[:10]}`" if o.commit else "")
            + (" · converged" if o.converged else "")
            + (f" · {u.get('num_turns')} turns" if u.get("num_turns") else "")
            + (f" · ${cost:.2f}" if isinstance(cost, int | float) else "")
            + (f" · {secs:.0f}s" if secs else "")
        )  # fmt: skip
    if o.checks != "skipped" or o.review != "skipped":
        lines.append(f"- checks: **{o.checks}** · review: **{o.review}**")
    nxt = {
        Action.DISPATCH: f"next: **{d.mode}**" + (f" phase {d.phase}" if d.phase else ""),
        Action.READY: "PR marked **ready for review**",
        Action.FAILED: "**factory stopped**: needs a human",
        Action.REPLAN: "**needs replan**: run `/factory-replan`, then hand over again",
        Action.PAUSED: "**paused**",
    }[d.action]
    lines.append(f"- {nxt} ({d.reason})")
    lines += ["", f"[workflow run]({run_url}) · attempts {d.state.attempts} · "
              f"converge {d.state.converge} · rework {d.state.rework}"]  # fmt: skip
    return "\n".join(lines) + "\n"


# --- GitHub ----------------------------------------------------------------------------------

Runner = Callable[..., subprocess.CompletedProcess[str]]


class GitHub:
    """The few `gh` calls the dispatcher makes (GH_TOKEN comes from the workflow)."""

    def __init__(self, repo: str, run: Runner = subprocess.run) -> None:
        self.repo, self._run = repo, run

    def gh(self, *args: str) -> str:
        proc = self._run(["gh", *args, "--repo", self.repo], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:2])}: {proc.stderr.strip()}")
        return str(proc.stdout)

    def pr(self, branch: str) -> dict[str, Any] | None:
        """The open PR for the branch, else its most recent closed one."""
        for state in ("open", "all"):
            out = self.gh("pr", "list", "--head", branch, "--state", state,
                          "--json", "number,body,labels,isDraft,url")  # fmt: skip
            prs: list[dict[str, Any]] = json.loads(out or "[]")
            if prs:
                return prs[0]
        return None

    def update(self, number: int, body: str, add: list[str], remove: list[str]) -> None:
        for label in add:
            self.gh("label", "create", label, "--force", "--color", "5319e7")
        args = ["pr", "edit", str(number), "--body", body]
        for label in add:
            args += ["--add-label", label]
        for label in remove:
            args += ["--remove-label", label]
        self.gh(*args)

    def comment(self, number: int, text: str) -> None:
        self.gh("pr", "comment", str(number), "--body", text)

    def ready(self, number: int) -> None:
        self.gh("pr", "ready", str(number))


LABELS = {
    Action.DISPATCH: WORKING,
    Action.READY: AWAITING,
    Action.FAILED: FAILED,
    Action.REPLAN: REPLAN,
}


def record(
    gh: GitHub, pr: dict[str, Any], o: Outcome, d: Decision, phases: list[tasks.Phase], url: str
) -> None:
    """Write the decision to the PR: marker and phase table, status label, comment, ready."""
    current = [lbl["name"] for lbl in pr.get("labels", [])]
    add = [LABELS[d.action]] if d.action in LABELS else []
    remove = [lbl for lbl in STATUS_LABELS if lbl in current and lbl not in add]
    gh.update(pr["number"], update_body(pr.get("body", ""), d.state, phases), add, remove)
    gh.comment(pr["number"], comment(o, d, url))
    if d.action is Action.READY and pr.get("isDraft"):
        gh.ready(pr["number"])


def outcome_from_files(
    step: str,
    phase: int | None,
    run_json: Path | None,
    checks: str,
    review: str,
    ci_report: Path | None,
    review_report: Path | None,
    reason: str = "",
) -> Outcome:
    """Build the Outcome from the agent's run.json and the CI and review reports."""

    def text(path: Path | None) -> str:
        return path.read_text(errors="replace") if path and path.is_file() else ""

    o = Outcome(
        Step(step), phase, checks=checks or "skipped", review=review or "skipped",
        ci_report=text(ci_report), review_report=text(review_report), reason=reason,
    )  # fmt: skip
    if run_json and run_json.is_file():
        rec = json.loads(run_json.read_text())
        res = rec.get("result") or {}
        status = res.get("status", "failed")
        why = str(res.get("reason") or "")
        o.agent = "ok" if status == "ok" else "timeout" if why.startswith("timeout") else (
            "refused" if status == "refused" else "failed")  # fmt: skip
        o.reason, o.log = why, str(res.get("log") or "")
        o.converged, o.commit = bool(res.get("converged")), str(res.get("commit") or "")
        o.phase = res.get("phase") or phase
        o.usage = rec.get("usage") or {}
    elif o.step in (Step.IMPLEMENT, Step.FIX, Step.CONVERGE, Step.REWORK):
        o.reason = o.reason or "the agent job did not produce a run record"
    return o
