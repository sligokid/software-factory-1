from pathlib import Path

import pytest
import yaml

from factory import preview
from factory.contract import Preview
from tests.conftest import git

PREVIEW = Preview(compose="compose.preview.yaml", service="web", port=8080, healthcheck="/health")


@pytest.mark.parametrize(
    ("branch", "pid"),
    [("feature/ENG-123", "eng-123"), ("feature/My_Feature.v2", "my-feature-v2"), ("x", "x")],
)
def test_preview_id(branch: str, pid: str) -> None:
    assert preview.preview_id(branch) == pid


def test_preview_url_needs_a_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(preview.DOMAIN_ENV, raising=False)
    assert preview.preview_url("feature/ENG-1") is None
    monkeypatch.setenv(preview.DOMAIN_ENV, "preview.example.dev")
    assert preview.preview_url("feature/ENG-1") == "https://eng-1.preview.example.dev"


def test_traffic_policy_auth_ips_and_commit_header() -> None:
    policy = preview.traffic_policy("abc", "u:p", ["10.0.0.0/8"])
    actions = [a for rule in policy["on_http_request"] for a in rule["actions"]]
    assert [a["type"] for a in actions] == ["restrict-ips", "basic-auth"]
    assert actions[1]["config"]["credentials"] == ["u:p"]
    header = policy["on_http_response"][0]["actions"][0]
    assert header["config"]["headers"] == {preview.COMMIT_HEADER: "abc"}


def test_override_adds_tunnel_only_with_a_url(tmp_path: Path) -> None:
    local = preview.override(PREVIEW, "abc", None, ["default"], tmp_path / "p.yml")
    assert local == {"services": {"web": {"labels": {preview.COMMIT_LABEL: "abc"}}}}
    public = preview.override(PREVIEW, "abc", "https://x.d", ["front"], tmp_path / "p.yml")
    tunnel = public["services"][preview.TUNNEL]
    assert tunnel["command"][-1] == "http://web:8080" and "https://x.d" in tunnel["command"]
    assert tunnel["networks"] == ["front"] and tunnel["environment"] == ["NGROK_AUTHTOKEN"]
    assert tunnel["labels"] == {preview.COMMIT_LABEL: "abc"}  # new commit -> tunnel recreated


def test_export_writes_the_commit_tree(repo: Path, tmp_path: Path) -> None:
    (repo / "app.txt").write_text("v1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "v1")
    dest = tmp_path / "src"
    (dest / "stale.txt").parent.mkdir(parents=True)
    (dest / "stale.txt").write_text("old")
    preview.export(repo, "HEAD", dest)
    assert (dest / "app.txt").read_text() == "v1\n"
    assert not (dest / "stale.txt").exists() and not (dest / ".git").exists()


def test_public_preview_requires_auth_or_ip_allowlist(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = yaml.safe_load((repo / ".factory" / "factory.yaml").read_text())
    contract["preview"] = {"compose": "compose.preview.yaml", "service": "web", "port": 80}
    (repo / ".factory" / "factory.yaml").write_text(yaml.safe_dump(contract))
    git(repo, "commit", "-qam", "preview")
    monkeypatch.setenv("NGROK_AUTHTOKEN", "t")
    monkeypatch.delenv(preview.AUTH_ENV, raising=False)
    monkeypatch.delenv(preview.ALLOW_IPS_ENV, raising=False)
    with pytest.raises(preview.PreviewError, match="never public"):
        preview.up(repo, "HEAD", "feature/X-1", domain="d.example")


def test_up_needs_a_preview_section(repo: Path) -> None:
    with pytest.raises(preview.PreviewError, match="no preview section"):
        preview.up(repo, "HEAD", "feature/X-1")
