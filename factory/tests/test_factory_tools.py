from pathlib import Path

import pytest

from factory.checks.sizes import find_violations
from factory.new_slice import create_slice


def test_create_slice_renders_template(tmp_path: Path) -> None:
    target = create_slice("prices", slices_dir=tmp_path)
    assert (target / "SLICE.md").read_text().startswith("# Slice: prices")
    assert 'prefix="/prices"' in (target / "api.py").read_text()


def test_create_slice_rejects_bad_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_slice("Bad-Name", slices_dir=tmp_path)


def test_size_limits(tmp_path: Path) -> None:
    limits = tmp_path / "limits.toml"
    limits.write_text('[files]\n"CLAUDE.md" = 2\n')
    (tmp_path / "CLAUDE.md").write_text("a\nb\nc\n")
    assert find_violations(tmp_path, limits) == ["CLAUDE.md: 3 lines (limit 2)"]


def test_repo_within_size_limits() -> None:
    assert find_violations() == []
