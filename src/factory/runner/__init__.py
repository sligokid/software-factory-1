"""Sandboxed headless Claude Code runs: images, entrypoint, egress proxy and host orchestration."""

import os
from enum import StrEnum

from factory import __version__


class Mode(StrEnum):
    IMPLEMENT = "implement"  # implement one phase of tasks.md as one commit
    FIX = "fix"  # fix the last phase commit after CI or review failed (amends it)
    CONVERGE = "converge"  # speckit-converge: append gaps as new phases, or report converged
    REWORK = "rework"  # address PR review comments as one new commit


AGENT_GIT_NAME = "factory-agent"  # author of agent commits; CI enforces protected paths on them
INPUT_REF = "refs/factory/input"  # the ref carrying the start commit into the container
IMAGE_PREFIX_ENV = "FACTORY_IMAGE_PREFIX"
DEFAULT_IMAGE_PREFIX = "software-factory/runner"


def image(runner: str) -> str:
    """Image tag for a contract runner (base | python | node), e.g. software-factory/runner-node."""
    prefix = os.environ.get(IMAGE_PREFIX_ENV, DEFAULT_IMAGE_PREFIX)
    return f"{prefix}-{runner}:{__version__}"
