from __future__ import annotations

from pathlib import Path

from local_translation_workbench.paths import (
    default_data_dir,
    find_source_root,
    migrations_dir,
)


def test_find_source_root_detects_checkout() -> None:
    root = Path(__file__).resolve().parents[1]

    assert find_source_root().resolve() == root.resolve()


def test_migrations_dir_points_to_existing_versions() -> None:
    versions = migrations_dir() / "versions"

    assert versions.exists()
    assert any(item.name.endswith("_initial_schema.py") for item in versions.iterdir())


def test_default_data_dir_uses_source_data_projects_in_checkout(monkeypatch) -> None:
    monkeypatch.delenv("LTW_DATA_DIR", raising=False)
    root = Path(__file__).resolve().parents[1]

    assert default_data_dir() == root / "data" / "projects"
