"""Prompts for each run mode. Product rules come from the repo (constitution, CLAUDE.md)."""

from factory.contract import Contract
from factory.runner import Mode
from factory.tasks import Phase

RULES = """
Rules for this run (you are running headless; nobody will answer questions):
- Follow .specify/memory/constitution.md and CLAUDE.md. Make reasonable decisions instead of
  asking; record any assumption in your final message.
- Never change .github/, .factory/, .specify/, .claude/, .mcp.json, CLAUDE.md or any path listed
  under `protected` in .factory/factory.yaml. Only {spec_dir}/ may change under specs/.
- Run `{verify}` before you finish and make it pass.{checks}
- Commit your work with git (any number of commits; the factory squashes them). Do not push.
"""


def _rules(contract: Contract, spec_dir: str) -> str:
    checks = f"\n- Run `{contract.checks}` and make it pass." if contract.checks else ""
    return RULES.format(spec_dir=spec_dir, verify=contract.verify, checks=checks)


def build(
    mode: Mode,
    contract: Contract,
    spec_dir: str,
    *,
    phase: Phase | None = None,
    feedback: str = "",
) -> str:
    tasks = f"{spec_dir}/tasks.md"
    if mode is Mode.IMPLEMENT:
        assert phase is not None
        body = (
            f"Use the speckit-implement skill to implement **only {phase.name}** of {tasks} "
            f"(tasks {phase.tasks[0].id}-{phase.tasks[-1].id}). Do not start any other phase. "
            f"Mark each task of this phase [X] in {tasks} as you complete it. Treat incomplete "
            "checklists as approved: do not stop to ask."
        )
    elif mode is Mode.FIX:
        assert phase is not None
        body = (
            f"The last commit implemented {phase.name} of {tasks}, but CI or the review failed. "
            "Fix the problems below without starting any other phase.\n\n"
            f"Failure report:\n```\n{feedback.strip()}\n```"
        )
    elif mode is Mode.CONVERGE:
        body = (
            f"Use the speckit-converge skill on {spec_dir}. If it finds gaps, it appends a new "
            f"phase to {tasks}; that is the only file you may change in this run. Do not change "
            "any code."
        )
    else:
        body = (
            "A reviewer requested changes on this feature's pull request. Address every comment "
            f"below, keeping to the spec in {spec_dir}.\n\n"
            f"Review comments:\n```\n{feedback.strip()}\n```"
        )
    return body + "\n" + _rules(contract, spec_dir)
