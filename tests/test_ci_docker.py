"""Every CI check fails on a bad commit and passes on a clean one, run inside the runner image the
way GitHub Actions runs it. Needs Docker, network (semgrep rules, OSV) and `make images`."""

import secrets
import subprocess
from pathlib import Path

import pytest

from factory.runner import image
from tests.conftest import git

pytestmark = pytest.mark.docker

CONTRACT = """version: 1
runner: base
commands:
  setup: 'true'
  verify: sh test.sh
  checks: sh arch.sh
limits:
  commit_lines: 40
"""
CLEAN = {
    ".factory/factory.yaml": CONTRACT,
    "test.sh": "grep -q ok status.txt\n",
    "arch.sh": "test ! -e forbidden.txt\n",
    "status.txt": "ok\n",
    "requirements.txt": "six==1.17.0\n",
    "app.py": "def greet(name: str) -> str:\n    return f'Hello, {name}!'\n",
}
SHELL_INJECTION = (
    "import subprocess\n\n\ndef run(cmd):\n    return subprocess.call(cmd, shell=True)\n"
)
BAD = {
    "verify": {"status.txt": "failing\n"},
    "checks": {"forbidden.txt": "x\n"},
    "factory": {"big.txt": "line\n" * 60},
    "secrets": {"config.py": f'GITHUB_TOKEN = "ghp_{secrets.token_hex(18)}"\n'},
    "sast": {"tool.py": SHELL_INJECTION},
    "deps": {"requirements.txt": "django==2.0.0\n"},
}


def _write(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD").strip()


def factory_ci(repo: Path, step: str, base: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker", "run", "--rm", "-v", f"{repo}:/repo", "-w", "/repo",
        "-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory",
        "-e", "GIT_CONFIG_VALUE_0=*",
        "--entrypoint", "factory", image("base"), "ci", step, "--base", base,
    ]  # fmt: skip
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


@pytest.fixture
def product(repo: Path) -> tuple[Path, str]:
    base = git(repo, "rev-parse", "HEAD").strip()
    _write(repo, CLEAN, "clean product")
    return repo, base


@pytest.mark.parametrize("step", list(BAD))
def test_check_passes_clean_and_fails_bad(product: tuple[Path, str], step: str) -> None:
    repo, base = product
    clean = factory_ci(repo, step, base)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    after_clean = git(repo, "rev-parse", "HEAD").strip()
    _write(repo, BAD[step], f"bad commit for {step}")
    bad = factory_ci(repo, step, after_clean)
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert f"FAIL  {step}" in bad.stdout
