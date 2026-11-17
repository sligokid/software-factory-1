"""The agent's tool allowlist and the headless `claude` command line.

The sandbox (network, filesystem, limits) is the real boundary; the allowlist keeps the agent to
git, Spec Kit scripts and the product's own commands from `.factory/factory.yaml`.
"""

import re

from factory.contract import Contract

FILE_TOOLS = ["Read", "Edit", "MultiEdit", "Write", "Glob", "Grep", "TodoWrite", "Skill"]
GIT_SUBCOMMANDS = [
    "status", "diff", "log", "show", "add", "commit", "restore", "rm", "mv", "rev-parse",
    "ls-files", "branch --show-current",
]  # fmt: skip
SPECKIT_SCRIPTS = [".specify/scripts/bash/*", "bash .specify/scripts/bash/*"]
DENIED = ["WebFetch", "WebSearch", "Bash(git push*)", "Bash(curl *)", "Bash(wget *)"]

_SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def command_parts(command: str) -> list[str]:
    """Simple commands in a shell command line, so each can be allowed on its own."""
    return [part.strip() for part in _SEPARATORS.split(command) if part.strip()]


def allowed_tools(contract: Contract) -> list[str]:
    rules = list(FILE_TOOLS)
    rules += [f"Bash(git {sub}*)" for sub in GIT_SUBCOMMANDS]
    rules += [f"Bash({script})" for script in SPECKIT_SCRIPTS]
    for command in (contract.setup, contract.verify, contract.checks):
        for part in command_parts(command or ""):
            rule = f"Bash({part}*)"
            if rule not in rules:
                rules.append(rule)
    return rules


def claude_command(
    prompt: str, contract: Contract, *, max_turns: int, model: str | None = None
) -> list[str]:
    cmd = [
        "claude",
        "--print",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "dontAsk",  # anything not allowed below is denied, never prompted
        "--strict-mcp-config",  # no MCP servers (e.g. the product's Linear config)
        "--no-session-persistence",
        "--allowedTools",
        *allowed_tools(contract),
        "--disallowedTools",
        *DENIED,
    ]
    if model:
        cmd += ["--model", model]
    return cmd
