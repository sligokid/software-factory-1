from pathlib import Path

import pytest

from factory.contract import (
    DEFAULT_PROTECTED,
    ContractError,
    load,
    parse,
    validation_errors,
)

MINIMAL = {"version": 1, "runner": "python", "commands": {"verify": "make all"}}


def test_minimal_contract_gets_defaults() -> None:
    contract = parse(MINIMAL)
    assert contract.runner == "python"
    assert contract.commit_lines == 300
    assert contract.protected == DEFAULT_PROTECTED
    assert contract.allowed_hosts[:1] == ["api.anthropic.com"]


def test_full_contract() -> None:
    contract = parse(
        {
            **MINIMAL,
            "commands": {"setup": "uv sync", "verify": "make all", "checks": "make check"},
            "preview": {"compose": "compose.preview.yaml", "service": "api", "port": 8000},
            "egress": ["pypi.org"],
            "limits": {"commit_lines": 200, "exclude": ["uv.lock"], "files": {"README.md": 50}},
            "protected": ["src/generated/**"],
        }
    )
    assert contract.preview is not None and contract.preview.port == 8000
    assert "pypi.org" in contract.allowed_hosts
    assert contract.exclude == ["specs/**", "uv.lock"]
    assert contract.file_limits["README.md"] == 50
    assert contract.protected[-1] == "src/generated/**"


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"version": 1, "runner": "python", "commands": {}}, "'verify' is a required property"),
        ({**MINIMAL, "runner": "cobol"}, "runner"),
        ({**MINIMAL, "unknown": True}, "Additional properties"),
        ({**MINIMAL, "egress": ["http://x"]}, "egress.0"),
    ],
)
def test_invalid_contracts(data: dict[str, object], fragment: str) -> None:
    assert any(fragment in e for e in validation_errors(data))
    with pytest.raises(ContractError):
        parse(data)


def test_load_missing(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="not found"):
        load(tmp_path)
