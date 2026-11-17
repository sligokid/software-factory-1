"""A local preview (no tunnel) is deployed, health-checked, redeployed to the latest commit and
removed. Needs Docker and `make images`."""

import subprocess
from pathlib import Path

import pytest

from factory import preview
from factory.runner import image
from tests.conftest import git

pytestmark = pytest.mark.docker

COMPOSE = """services:
  web:
    image: busybox:1.37
    environment:
      FACTORY_COMMIT: ${FACTORY_COMMIT}
    command:
      - sh
      - -c
      - mkdir -p /www && echo $$FACTORY_COMMIT > /www/index.html && echo ok > /www/health
        && httpd -f -p 8080 -h /www
"""
CONTRACT = """version: 1
runner: base
commands:
  verify: 'true'
preview:
  compose: compose.preview.yaml
  service: web
  port: 8080
  healthcheck: /health
"""
BRANCH = "feature/PREVIEW-TEST"


def served(pid: str) -> str:
    cmd = ["docker", "run", "--rm", "--network", f"{preview.project(pid)}_default"]
    cmd += ["--entrypoint", "curl", image("base"), "-fsS", "http://web:8080/"]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def test_preview_up_redeploy_down(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(preview.STATE_ENV, str(tmp_path_factory.mktemp("previews")))
    monkeypatch.delenv(preview.DOMAIN_ENV, raising=False)
    (repo / "compose.preview.yaml").write_text(COMPOSE)
    (repo / ".factory" / "factory.yaml").write_text(CONTRACT)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "preview v1")
    pid = preview.preview_id(BRANCH)
    preview.down(BRANCH)
    try:
        first = preview.up(repo, "HEAD", BRANCH, timeout=60)
        assert first.url is None and served(pid) == first.commit

        (repo / "app.txt").write_text("v2\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "v2")
        second = preview.up(repo, "HEAD", BRANCH, timeout=60)
        assert second.commit != first.commit and served(pid) == second.commit
        assert [r["commit"] for r in preview.status() if r["id"] == pid] == [second.commit]
    finally:
        assert preview.down(BRANCH)
    ps = [
        "docker",
        "ps",
        "-aq",
        "--filter",
        f"label=com.docker.compose.project={preview.project(pid)}",
    ]
    assert subprocess.run(ps, capture_output=True, text=True).stdout.strip() == ""
