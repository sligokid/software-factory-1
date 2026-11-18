from pathlib import Path

import pytest
import yaml

from factory import __version__
from factory.cli import main
from factory.init import CI_WORKFLOW, init_product

ROOT = Path(__file__).parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
KIT_WORKFLOW = ROOT / "src" / "factory" / "kit" / "factory-ci.yml"


@pytest.mark.parametrize("path", [*WORKFLOWS, KIT_WORKFLOW], ids=lambda p: p.name)
def test_workflows_are_valid_yaml(path: Path) -> None:
    data = yaml.safe_load(path.read_text())
    assert data["jobs"]


def test_product_workflow_pulls_images_of_this_version() -> None:
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "product.yml").read_text())
    assert data["env"]["FACTORY_VERSION"] == __version__
    assert set(data["jobs"]) == {"context", "checks", "review", "preview"}
    steps = " ".join(str(s.get("run", "")) for s in data["jobs"]["checks"]["steps"])
    for step in ("setup", "verify", "checks", "factory", "secrets", "sast", "deps"):
        assert f"factory ci {step}" in steps


def test_kit_workflow_calls_the_reusable_workflow() -> None:
    data = yaml.safe_load(KIT_WORKFLOW.read_text())
    assert data["jobs"]["factory"]["uses"].endswith("/.github/workflows/product.yml@v1")
    assert data[True]["pull_request"]["types"] == ["ready_for_review", "closed"]  # `on:` key


def test_init_installs_ci_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("factory.init.run_speckit_init", lambda _: None)
    init_product(tmp_path / "a", factory_repo="Acme/factory-2")
    text = (tmp_path / "a" / CI_WORKFLOW).read_text()
    assert "uses: Acme/factory-2/.github/workflows/product.yml@v1\n" in text
    assert "image-prefix: ghcr.io/acme/factory-2/runner\n" in text  # where images.yml publishes
    init_product(tmp_path / "b")
    assert main(["validate", "--root", str(tmp_path / "b")]) == 0
    assert f"{CI_WORKFLOW}: set the factory repository" in capsys.readouterr().out
