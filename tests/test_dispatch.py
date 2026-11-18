import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from factory import dispatch, tasks
from factory.contract import Contract
from factory.dispatch import Action, Decision, Outcome, State, Step, decide

CONTRACT = Contract(runner="base", verify="true")  # limits: 2 fixes, 2 converge, 2 rework
TWO_PHASES = """## Phase 1: A
- [X] T001 a
## Phase 2: B
- [ ] T002 b
"""
ALL_DONE = TWO_PHASES.replace("- [ ] T002", "- [X] T002")


def phases(text: str = TWO_PHASES) -> list[tasks.Phase]:
    return tasks.parse(text)


def ok(step: Step = Step.IMPLEMENT, **kw: Any) -> Outcome:
    base: dict[str, Any] = {"phase": 1, "agent": "ok", "commit": "abc1234567", "checks": "success",
                            "review": "success"}  # fmt: skip
    return Outcome(step, **(base | kw))


def test_passing_phase_dispatches_the_next_open_phase() -> None:
    d = decide(ok(), phases(), State(attempts=1), CONTRACT, [])
    assert (d.action, d.mode, d.phase) == (Action.DISPATCH, "implement", 2)
    assert d.state.attempts == 0 and d.state.runs == 1


def test_all_phases_done_dispatches_converge_then_final() -> None:
    d = decide(ok(), phases(ALL_DONE), State(), CONTRACT, [])
    assert (d.action, d.mode) == (Action.DISPATCH, "converge")
    d = decide(
        ok(Step.CONVERGE, converged=True, commit=""), phases(ALL_DONE), State(), CONTRACT, []
    )
    assert (d.action, d.mode) == (Action.DISPATCH, "final")


def test_converge_that_adds_a_phase_implements_it_within_the_round_limit() -> None:
    d = decide(ok(Step.CONVERGE), phases(), State(), CONTRACT, [])
    assert (d.mode, d.phase, d.state.converge) == ("implement", 2, 1)
    d = decide(ok(Step.CONVERGE), phases(), State(converge=2), CONTRACT, [])
    assert d.action is Action.FAILED


def test_failed_checks_dispatch_a_fix_with_the_reports_then_stop_at_the_limit() -> None:
    o = ok(checks="failure", review="skipped", ci_report="FAIL verify", review_report="")
    d = decide(o, phases(), State(), CONTRACT, [])
    assert (d.action, d.mode, d.phase) == (Action.DISPATCH, "fix", 1)
    assert "FAIL verify" in d.feedback and d.state.attempts == 1
    d = decide(o, phases(), State(attempts=2), CONTRACT, [])
    assert d.action is Action.FAILED and "2 fix attempt" in d.reason


def test_blocking_review_also_dispatches_a_fix() -> None:
    o = ok(review="failure", review_report="blocking: missing test")
    d = decide(o, phases(), State(), CONTRACT, [])
    assert d.mode == "fix" and "missing test" in d.feedback and "review failed" in d.reason


def test_agent_failure_retries_the_same_step_with_the_reason() -> None:
    o = Outcome(Step.IMPLEMENT, phase=2, agent="failed", reason="verify failed (exit 1)", log="E")
    d = decide(o, phases(), State(), CONTRACT, [])
    assert (d.mode, d.phase) == ("implement", 2) and "verify failed" in d.feedback


@pytest.mark.parametrize("agent", ["timeout", "refused", "none"])
def test_timeout_refusal_or_missing_run_stop_the_factory(agent: str) -> None:
    d = decide(Outcome(Step.IMPLEMENT, phase=1, agent=agent), phases(), State(), CONTRACT, [])
    assert d.action is Action.FAILED


def test_final_review_marks_ready_or_reworks_within_the_limit() -> None:
    passed = Outcome(Step.FINAL, review="success")
    assert decide(passed, phases(ALL_DONE), State(), CONTRACT, []).action is Action.READY
    blocked = Outcome(Step.FINAL, review="failure", review_report="blocking")
    d = decide(blocked, phases(ALL_DONE), State(), CONTRACT, [])
    assert (d.mode, d.state.rework, d.feedback) == ("rework", 1, "blocking")
    assert decide(blocked, phases(ALL_DONE), State(rework=2), CONTRACT, []).action is Action.FAILED


def test_takeover_label_pauses_and_replan_stops() -> None:
    assert decide(ok(), phases(), State(), CONTRACT, ["human-takeover"]).action is Action.PAUSED
    d = decide(Outcome(Step.REPLAN, reason="PR closed"), phases(), State(), CONTRACT, [])
    assert (d.action, d.reason) == (Action.REPLAN, "PR closed")


def test_feedback_is_clipped_to_its_tail() -> None:
    o = ok(checks="failure", ci_report="x" * 30_000 + "END")
    d = decide(o, phases(), State(), CONTRACT, [])
    assert len(d.feedback) < 21_000 and d.feedback.endswith("END")


def test_state_and_phase_table_round_trip_in_the_pr_body() -> None:
    body = "Spec: specs/001\n<!-- factory:spec=specs/001 id=X source=document -->"
    assert dispatch.read_state(body) == State()
    once = dispatch.update_body(body, State(attempts=1, runs=3), phases())
    assert dispatch.read_state(once) == State(attempts=1, runs=3)
    assert "| Phase 1: A | T001-T001 | ✅ |" in once and "| Phase 2: B | T002-T002 | 0/1 |" in once
    twice = dispatch.update_body(once, State(runs=4), phases(ALL_DONE))
    assert twice.count("factory:state") == 1 and twice.count("### Factory progress") == 1
    assert dispatch.read_state(twice).runs == 4 and "0/1" not in twice


def test_outcome_from_the_run_record(tmp_path: Path) -> None:
    run = tmp_path / "run.json"
    result = {"status": "failed", "reason": "timeout after 3600s", "phase": 2}
    run.write_text(json.dumps({"result": result, "usage": {"num_turns": 9}}))
    o = dispatch.outcome_from_files("implement", None, run, "skipped", "skipped", None, None)
    assert (o.agent, o.phase, o.usage["num_turns"]) == ("timeout", 2, 9)
    missing = dispatch.outcome_from_files("fix", 1, tmp_path / "nope", "", "", None, None)
    assert missing.agent == "none" and "did not produce" in missing.reason


class FakeGh:
    def __init__(self, prs: list[dict[str, Any]]) -> None:
        self.calls: list[list[str]] = []
        self.prs = prs

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        out = json.dumps(self.prs) if cmd[1:3] == ["pr", "list"] else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_record_sets_labels_body_comment_and_ready() -> None:
    pr = {"number": 7, "body": "b", "isDraft": True, "labels": [{"name": "factory:working"}]}
    fake = FakeGh([pr])
    gh = dispatch.GitHub("o/r", fake)
    assert gh.pr("feature/X") == pr
    d = Decision(Action.READY, State(runs=5), reason="whole-PR review passed")
    dispatch.record(gh, pr, Outcome(Step.FINAL, review="success"), d, phases(ALL_DONE), "URL")
    edit = next(c for c in fake.calls if c[1:3] == ["pr", "edit"])
    assert edit[edit.index("--add-label") + 1] == "factory:awaiting-review"
    assert edit[edit.index("--remove-label") + 1] == "factory:working"
    assert "factory:state" in edit[edit.index("--body") + 1]
    note = next(c for c in fake.calls if c[1:3] == ["pr", "comment"])
    assert "ready for review" in note[note.index("--body") + 1]
    assert ["gh", "pr", "ready", "7", "--repo", "o/r"] in fake.calls


def test_next_command_dry_run(
    product: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from factory.cli import main

    out = product / "gh-out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(
        dispatch.GitHub, "pr", lambda self, branch: {"number": 1, "body": "", "labels": []}
    )
    run = product / "run.json"
    run.write_text(json.dumps({"result": {"status": "ok", "phase": 1, "commit": "c0ffee"}}))
    args = ["next", "--step", "implement", "--root", str(product), "--run-json", str(run),
            "--checks", "success", "--review", "skipped", "--dry-run", "--branch", "feature/DEMO-1",
            "--feedback-out", str(product / "fb.txt")]  # fmt: skip
    assert main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    # DEMO-1 phase 1 is still open in the fixture: the dispatcher asks for it again as "next".
    assert printed["action"] == "dispatch" and printed["mode"] == "implement"
    assert "action=dispatch\n" in out.read_text()


def test_ready_failure_is_reported_not_fatal() -> None:
    pr = {"number": 7, "body": "", "isDraft": True, "labels": []}

    def run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        code = 1 if cmd[1:3] == ["pr", "ready"] else 0
        return subprocess.CompletedProcess(cmd, code, "", "Resource not accessible")

    calls: list[list[str]] = []
    gh = dispatch.GitHub("o/r", lambda cmd, **kw: (calls.append(cmd), run(cmd))[1])
    d = Decision(Action.READY, State(), reason="whole-PR review passed")
    dispatch.record(gh, pr, Outcome(Step.FINAL, review="success"), d, phases(ALL_DONE), "URL")
    notes = [c[c.index("--body") + 1] for c in calls if c[1:3] == ["pr", "comment"]]
    assert any("Mark it **ready for review**" in n for n in notes)
