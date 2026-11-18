"""`factory review`: a read-only Claude Code reviewer, against the product's constitution and spec.

It reviews the commits in base..head (one phase commit, or a whole PR), optionally with
screenshots of the preview, and returns a structured verdict. Any `blocking` finding fails it.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from factory.checks import git
from factory.contract import Contract
from factory.init import CONSTITUTION

READ_TOOLS = ["Read", "Grep", "Glob", "TodoWrite"]
READ_GIT = ["diff", "log", "show", "status", "ls-files", "rev-parse", "blame"]
DENIED = [
    "Edit", "MultiEdit", "Write", "NotebookEdit", "WebFetch", "WebSearch",
    "Bash(git commit*)", "Bash(git push*)", "Bash(git checkout*)", "Bash(git reset*)",
]  # fmt: skip
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "findings"],
    "properties": {
        "summary": {"type": "string", "description": "2-5 sentences on the change and its quality"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "rule", "message"],
                "properties": {
                    "severity": {"enum": ["blocking", "advisory"]},
                    "rule": {
                        "type": "string",
                        "description": "Constitution section heading or spec requirement id",
                    },
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "message": {"type": "string"},
                },
            },
        },
    },
}

PROMPT = """You are the factory's code reviewer for this repository. You are read-only: you can
read files and run read-only git commands, nothing else.

Review the changes in `git diff {base}...{head}` (three dots). Commits:
{commits}

Judge them against:
1. {constitution}: the product principles and the factory sections. This is the main standard.
2. {spec}
3. Correctness, tests for every behaviour change, security and maintainability.
{screenshots}
Report each problem once, in a file and line of the diff where possible. Use severity:
- `blocking`: violates a MUST in the constitution, contradicts the spec, is a bug, a security
  problem, or a behaviour change without tests.
- `advisory`: anything else worth fixing (naming, clarity, small simplifications).
`rule` names the constitution section heading (e.g. "Factory: Agent Boundaries") or the spec
requirement id (e.g. FR-003) the finding is based on; use "General" otherwise. Only review what
these commits change. The `{verify}` command has already passed; do not run it.
"""


class ReviewError(RuntimeError):
    """The reviewer could not run or returned no verdict."""


@dataclass
class Review:
    base: str
    head: str
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> list[dict[str, Any]]:
        return [f for f in self.findings if f.get("severity") == "blocking"]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": "pass" if self.passed else "fail",
            "base": self.base,
            "head": self.head,
            "summary": self.summary,
            "findings": self.findings,
            "usage": self.usage,
        }


def screenshots_in(folder: Path | None) -> list[Path]:
    if folder is None or not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)


def build_prompt(
    root: Path,
    contract: Contract,
    base: str,
    head: str,
    spec_dir: str | None,
    screenshots: list[Path],
    addressing: str = "",
) -> str:
    commits = git.commits(root, base, head)
    listed = "\n".join(f"- {c.sha[:10]} {c.subject} ({c.author})" for c in commits) or "- (none)"
    spec = (
        f"{spec_dir}/spec.md, plan.md and tasks.md: the feature being built. Phases whose tasks "
        "are checked must be fully implemented."
        if spec_dir
        else "The commit messages (no feature spec was found for this branch)."
    )
    shots = ""
    if screenshots:
        files = "\n".join(f"- {p}" for p in screenshots)
        shots = (
            "\nScreenshots of the running preview at this commit (open each with Read and check "
            f"the UI against the spec; broken or empty pages are blocking):\n{files}\n"
        )
    if addressing.strip():
        shots += (
            "\nThese commits were made to resolve the CI failures or review findings below. "
            "Changes needed to resolve them are in scope even outside the phase's tasks; check "
            f"that each one is resolved:\n```\n{addressing.strip()[-8000:]}\n```\n"
        )
    return PROMPT.format(
        base=base,
        head=head,
        commits=listed,
        constitution=CONSTITUTION.as_posix(),
        spec=spec,
        screenshots=shots,
        verify=contract.verify,
    )


def claude_command(
    prompt: str, contract: Contract, *, max_turns: int, model: str | None, extra_dirs: list[Path]
) -> list[str]:
    allowed = list(READ_TOOLS) + [f"Bash(git {sub}*)" for sub in READ_GIT]
    cmd = [
        "claude", "--print", prompt,
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
        "--max-turns", str(max_turns),
        "--permission-mode", "dontAsk",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]  # fmt: skip
    for folder in extra_dirs:
        cmd += ["--add-dir", str(folder)]
    cmd += ["--allowedTools", *allowed, "--disallowedTools", *DENIED]
    if model:
        cmd += ["--model", model]
    return cmd


def parse_output(stdout: str, base: str, head: str) -> Review:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise ReviewError(f"reviewer output is not JSON: {stdout[-500:]}") from exc
    output = data.get("structured_output")
    if data.get("is_error") or not isinstance(output, dict):
        raise ReviewError(
            f"reviewer returned no verdict: {data.get('subtype')} {data.get('result')}"
        )
    usage = {k: data.get(k) for k in ("num_turns", "duration_ms", "total_cost_usd")}
    return Review(base, head, str(output.get("summary", "")), list(output["findings"]), usage)


def review(
    root: Path,
    contract: Contract,
    base: str,
    head: str = "HEAD",
    *,
    spec_dir: str | None = None,
    screenshots: Path | None = None,
    max_turns: int = 40,
    model: str | None = None,
    addressing: str = "",
) -> Review:
    if "ANTHROPIC_API_KEY" in os.environ:
        raise ReviewError(
            "ANTHROPIC_API_KEY is set: the factory only runs on a Claude subscription"
        )
    shots = screenshots_in(screenshots)
    prompt = build_prompt(root, contract, base, head, spec_dir, shots, addressing)
    extra = [screenshots.resolve()] if screenshots and shots else []
    cmd = claude_command(prompt, contract, max_turns=max_turns, model=model, extra_dirs=extra)
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise ReviewError(f"claude exited {proc.returncode}: {proc.stderr[-500:]}")
    return parse_output(proc.stdout, base, head)


def markdown(result: Review) -> str:
    verdict = "pass" if result.passed else "changes required"
    icon = "✅" if result.passed else "❌"
    lines = [
        f"## {icon} Factory review: {verdict}",
        "",
        f"`{result.base[:10]}..{result.head[:10]}` · {len(result.blocking)} blocking · "
        f"{len(result.findings) - len(result.blocking)} advisory",
        "",
        result.summary,
    ]
    if result.findings:
        lines += ["", "| Severity | Where | Rule | Finding |", "|---|---|---|---|"]
        ordered = sorted(result.findings, key=lambda f: f.get("severity") != "blocking")
        for f in ordered:
            where = f.get("file", "")
            if where and f.get("line"):
                where = f"{where}:{f['line']}"
            message = str(f.get("message", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {f.get('severity')} | `{where}` | {f.get('rule', '')} | {message} |")
    lines += ["", "<!-- factory:review -->"]
    return "\n".join(lines) + "\n"
