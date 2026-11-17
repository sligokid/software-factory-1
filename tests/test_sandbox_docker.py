"""Sandbox behaviour against the real runner image. Needs Docker, network and `make images`.

Run with `make docker-test` (sets FACTORY_DOCKER_TESTS=1); skipped otherwise.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from factory.runner import Mode, host, image, sandbox

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTORY_DOCKER_TESTS") != "1", reason="set FACTORY_DOCKER_TESTS=1"
)
IMAGE = image("base")


def docker_run(*args: str, network: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "run", "--rm", *sandbox.hardening(sandbox.Limits())]
    if network:
        proxy = f"http://{sandbox.PROXY_ALIAS}:{sandbox.PROXY_PORT}"
        cmd += ["--network", network, "-e", f"HTTPS_PROXY={proxy}"]
    return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def network(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    name = "factory-sandbox-test"
    host._stop_sandbox(name, tmp_path_factory.mktemp("cleanup"))
    host._start_sandbox(name, IMAGE, ["api.anthropic.com", "github.com"])
    yield name
    host._stop_sandbox(name, tmp_path_factory.mktemp("logs"))


def test_api_key_stops_the_container() -> None:
    result = docker_run("-e", "ANTHROPIC_API_KEY=sk-test", "-e", "CLAUDE_CODE_OAUTH_TOKEN=x", IMAGE)
    assert result.returncode == 2
    assert '"status": "refused"' in result.stdout


def test_missing_oauth_token_stops_the_container() -> None:
    assert docker_run(IMAGE).returncode == 2


def test_non_root_read_only_and_tools_present() -> None:
    script = "id -u; touch /usr/x 2>/dev/null && echo writable; claude --version; specify --help >/dev/null && echo speckit; git --version; gh --version | head -1"  # noqa: E501
    result = docker_run("--entrypoint", "sh", IMAGE, "-c", script)
    lines = result.stdout.splitlines()
    assert lines[0] == "10001"
    assert "writable" not in result.stdout
    assert "Claude Code" in result.stdout and "speckit" in lines


def _curl(network: str, url: str, *extra: str) -> subprocess.CompletedProcess[str]:
    args = ["--entrypoint", "curl", IMAGE, "-sS", "-m", "15", "-o", "/dev/null"]
    return docker_run(*args, "-w", "%{http_code}", *extra, url, network=network)


def test_allowlisted_host_is_reachable(network: str) -> None:
    result = _curl(network, "https://api.anthropic.com/")
    assert result.returncode == 0, result.stderr
    assert result.stdout != "000"


def test_other_hosts_are_refused(network: str, tmp_path: Path) -> None:
    refused = _curl(network, "https://example.com/")
    assert refused.returncode != 0
    assert "403" in refused.stderr


def test_no_route_around_the_proxy(network: str) -> None:
    direct = _curl(network, "https://github.com/", "--noproxy", "*")
    assert direct.returncode != 0
    raw_ip = _curl(network, "https://1.1.1.1/", "--noproxy", "*")
    assert raw_ip.returncode != 0


STAND_IN_CLAUDE = r"""#!/bin/sh
set -e
echo hello > app.txt
sed -i 's/- \[ \] T001/- [X] T001/; s/- \[ \] T002/- [X] T002/' specs/001-demo/tasks.md
git add -A && git commit -qm wip
echo '{"type": "result", "num_turns": 3, "total_cost_usd": 0}'
"""


@pytest.fixture(scope="module")
def stand_in_image(tmp_path_factory: pytest.TempPathFactory) -> str:
    """The runner image with `claude` replaced by a script that implements DEMO-1 phase 1."""
    ctx = tmp_path_factory.mktemp("image")
    (ctx / "claude").write_text(STAND_IN_CLAUDE)
    (ctx / "Dockerfile").write_text(
        f"FROM {IMAGE}\nCOPY --chmod=0755 claude /usr/local/bin/claude\n"
    )
    tag = "software-factory/runner-test:stand-in"
    subprocess.run(["docker", "build", "-q", "-t", tag, str(ctx)], check=True, capture_output=True)
    return tag


def test_agent_run_lands_one_commit_on_the_branch(
    product: Path,
    stand_in_image: str,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "stand-in")
    base = subprocess.run(
        ["git", "-C", str(product), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    run_dir = tmp_path_factory.mktemp("agent-run")
    req = host.RunRequest(product, "feature/DEMO-1", Mode.IMPLEMENT, image=stand_in_image)
    assert host.agent(req, run_dir) == 0
    log = subprocess.run(
        ["git", "-C", str(product), "log", "--format=%s", f"{base}..feature/DEMO-1"],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert log == ["DEMO-1: Phase 1: Setup"]
    assert (product / "app.txt").read_text() == "hello\n"  # checked-out branch was moved
    for name in ("run.json", "transcript.jsonl", "runner.log", "egress.log"):
        assert (run_dir / name).is_file()
