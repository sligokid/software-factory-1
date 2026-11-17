import json
import shutil
from pathlib import Path

import pytest

from factory.cli import main
from factory.contract import load
from factory.init import init_product


def test_init_without_speckit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = init_product(tmp_path / "shop", speckit=False)
    root = tmp_path / "shop"
    assert ".factory/factory.yaml" in report.created
    assert (root / ".claude/skills/factory-start/SKILL.md").exists()
    assert (root / ".claude/skills/factory-handoff/SKILL.md").exists()
    assert (root / ".claude/skills/factory-replan/SKILL.md").exists()
    constitution = (root / ".specify/memory/constitution.md").read_text()
    assert constitution.startswith("# shop Constitution")
    assert "[RATIFICATION_DATE]" not in constitution
    assert "linear" in json.loads((root / ".mcp.json").read_text())["mcpServers"]
    load(root)

    assert main(["validate", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "placeholder still set" in out
    assert "product section not filled in yet" in out


def test_init_keeps_product_files(tmp_path: Path) -> None:
    init_product(tmp_path, speckit=False)
    (tmp_path / "CLAUDE.md").write_text("mine\n")
    constitution = tmp_path / ".specify/memory/constitution.md"
    constitution.write_text("# My Constitution\n")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {}}}))

    report = init_product(tmp_path, speckit=False)
    assert (tmp_path / "CLAUDE.md").read_text() == "mine\n"
    assert constitution.read_text() == "# My Constitution\n"
    assert ".claude/skills/factory-start/SKILL.md" in report.updated
    servers = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"other", "linear"}


@pytest.mark.skipif(shutil.which("specify") is None, reason="Spec Kit CLI not installed")
def test_init_with_speckit(tmp_path: Path) -> None:
    init_product(tmp_path, name="web", speckit=True)
    assert (tmp_path / ".claude/skills/speckit-specify/SKILL.md").exists()
    assert (tmp_path / ".specify/templates/tasks-template.md").exists()
    constitution = (tmp_path / ".specify/memory/constitution.md").read_text()
    assert constitution.startswith("# web Constitution")
