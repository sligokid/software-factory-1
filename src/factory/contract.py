"""Load and validate a product's .factory/factory.yaml contract."""

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

CONTRACT_PATH = Path(".factory") / "factory.yaml"

DEFAULT_COMMIT_LINES = 300
DEFAULT_FIXES = 2
DEFAULT_CONVERGE_ROUNDS = 2
DEFAULT_REWORK_ROUNDS = 2
DEFAULT_EXCLUDE = ["specs/**"]
DEFAULT_FILE_LIMITS = {"CLAUDE.md": 120, ".specify/memory/constitution.md": 250}
DEFAULT_PROTECTED = [
    ".github/**",
    ".factory/**",
    ".claude/**",
    ".specify/**",
    "CLAUDE.md",
    ".mcp.json",
]
ALWAYS_ALLOWED_HOSTS = ["api.anthropic.com", "github.com", "api.github.com"]


class ContractError(ValueError):
    """The contract file is missing or invalid."""


@dataclass(frozen=True)
class Preview:
    compose: str
    service: str
    port: int
    healthcheck: str = "/"
    ui: bool = False
    screenshots: list[str] = field(default_factory=lambda: ["/"])


@dataclass(frozen=True)
class Contract:
    runner: str
    verify: str
    setup: str | None = None
    checks: str | None = None
    preview: Preview | None = None
    egress: list[str] = field(default_factory=list)
    commit_lines: int = DEFAULT_COMMIT_LINES
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    file_limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_FILE_LIMITS))
    protected: list[str] = field(default_factory=lambda: list(DEFAULT_PROTECTED))
    fixes: int = DEFAULT_FIXES
    converge_rounds: int = DEFAULT_CONVERGE_ROUNDS
    rework_rounds: int = DEFAULT_REWORK_ROUNDS

    @property
    def allowed_hosts(self) -> list[str]:
        return ALWAYS_ALLOWED_HOSTS + [h for h in self.egress if h not in ALWAYS_ALLOWED_HOSTS]


def schema() -> dict[str, Any]:
    text = resources.files("factory").joinpath("factory.schema.json").read_text()
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def validation_errors(data: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def _merge(defaults: list[str], extra: list[str]) -> list[str]:
    return defaults + [item for item in extra if item not in defaults]


def parse(data: Any) -> Contract:
    errors = validation_errors(data)
    if errors:
        raise ContractError("invalid factory.yaml:\n  " + "\n  ".join(errors))
    commands = data["commands"]
    limits = data.get("limits", {})
    preview = data.get("preview")
    return Contract(
        runner=data["runner"],
        verify=commands["verify"],
        setup=commands.get("setup"),
        checks=commands.get("checks"),
        preview=Preview(**preview) if preview else None,
        egress=list(data.get("egress", [])),
        commit_lines=limits.get("commit_lines", DEFAULT_COMMIT_LINES),
        exclude=_merge(DEFAULT_EXCLUDE, limits.get("exclude", [])),
        file_limits={**DEFAULT_FILE_LIMITS, **limits.get("files", {})},
        protected=_merge(DEFAULT_PROTECTED, data.get("protected", [])),
        fixes=limits.get("fixes", DEFAULT_FIXES),
        converge_rounds=limits.get("converge_rounds", DEFAULT_CONVERGE_ROUNDS),
        rework_rounds=limits.get("rework_rounds", DEFAULT_REWORK_ROUNDS),
    )


def load(product_root: Path) -> Contract:
    path = product_root / CONTRACT_PATH
    if not path.is_file():
        raise ContractError(f"{CONTRACT_PATH} not found in {product_root}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ContractError(f"{CONTRACT_PATH} is not valid YAML: {exc}") from exc
    return parse(data)
