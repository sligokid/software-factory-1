"""`factory init`: make a repository a factory product (Spec Kit + factory kit + contract)."""

import datetime as dt
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from factory import SPECKIT_VERSION
from factory.contract import CONTRACT_PATH

CONSTITUTION = Path(".specify") / "memory" / "constitution.md"
SPECKIT_TEMPLATE_MARKER = "[PROJECT_NAME]"


class InitError(RuntimeError):
    """Initialisation could not complete."""


@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def _kit() -> Traversable:
    return resources.files("factory").joinpath("kit")


def _speckit_version() -> str | None:
    if shutil.which("specify") is None:
        return None
    out = subprocess.run(["specify", "--version"], capture_output=True, text=True, check=False)
    return out.stdout.strip().rsplit(" ", 1)[-1] or None


def run_speckit_init(root: Path) -> None:
    version = _speckit_version()
    if version is None:
        raise InitError(
            "Spec Kit CLI not found. Install it with: "
            f"uv tool install specify-cli=={SPECKIT_VERSION}"
        )
    if version != SPECKIT_VERSION:
        raise InitError(
            f"Spec Kit {version} found, factory requires {SPECKIT_VERSION}: "
            f"uv tool install --force specify-cli=={SPECKIT_VERSION}"
        )
    subprocess.run(
        ["specify", "init", "--here", "--force", "--non-interactive", "--integration", "claude"],
        cwd=root,
        check=True,
    )


def _write_if_missing(root: Path, rel: Path, text: str, report: InitReport) -> None:
    path = root / rel
    if path.exists():
        report.kept.append(rel.as_posix())
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    report.created.append(rel.as_posix())


def _install_skills(root: Path, report: InitReport) -> None:
    skills = _kit().joinpath("skills")
    for skill in sorted(skills.iterdir(), key=lambda t: t.name):
        rel = Path(".claude") / "skills" / skill.name / "SKILL.md"
        path = root / rel
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(skill.joinpath("SKILL.md").read_text())
        (report.updated if existed else report.created).append(rel.as_posix())


def _install_constitution(root: Path, name: str, report: InitReport) -> None:
    path = root / CONSTITUTION
    if path.exists() and SPECKIT_TEMPLATE_MARKER not in path.read_text():
        report.kept.append(CONSTITUTION.as_posix())
        return
    today = dt.date.today().isoformat()
    text = (
        _kit()
        .joinpath("constitution.md")
        .read_text()
        .replace("[PRODUCT_NAME]", name)
        .replace("[RATIFICATION_DATE]", today)
    )
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    (report.updated if existed else report.created).append(CONSTITUTION.as_posix())


def _install_mcp(root: Path, report: InitReport) -> None:
    rel = Path(".mcp.json")
    path = root / rel
    kit_servers = json.loads(_kit().joinpath("mcp.json").read_text())["mcpServers"]
    if not path.exists():
        path.write_text(json.dumps({"mcpServers": kit_servers}, indent=2) + "\n")
        report.created.append(rel.as_posix())
        return
    config = json.loads(path.read_text())
    servers = config.setdefault("mcpServers", {})
    if all(k in servers for k in kit_servers):
        report.kept.append(rel.as_posix())
        return
    for key, value in kit_servers.items():
        servers.setdefault(key, value)
    path.write_text(json.dumps(config, indent=2) + "\n")
    report.updated.append(rel.as_posix())


def init_product(root: Path, *, name: str | None = None, speckit: bool = True) -> InitReport:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = InitReport()
    if speckit:
        run_speckit_init(root)
    kit = _kit()
    _install_constitution(root, name or root.name, report)
    _install_skills(root, report)
    _write_if_missing(root, CONTRACT_PATH, kit.joinpath("factory.yaml").read_text(), report)
    _write_if_missing(root, Path("CLAUDE.md"), kit.joinpath("CLAUDE.md").read_text(), report)
    _write_if_missing(
        root,
        Path(".factory") / "linear-issue-template.md",
        kit.joinpath("linear-issue-template.md").read_text(),
        report,
    )
    _install_mcp(root, report)
    return report
