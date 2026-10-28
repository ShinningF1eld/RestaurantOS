"""Image schema evidence must identify the allocated database and fail closed."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def load(monkeypatch, stdout):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "image_checker", root / "scripts/check-backend-image.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "run_docker",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout, ""),
    )
    return module


@pytest.mark.parametrize("tables", [[], ["alembic_version", "users"]])
def test_schema_evidence_preserves_tables_for_startup_migration_check(
    monkeypatch, tables
):
    checker = load(
        monkeypatch, json.dumps({"database": "owned_test", "public_tables": tables})
    )
    assert checker.verify_container_database_connection(
        "owned-container",
        {"DATABASE_URL": "postgresql+asyncpg://example.invalid/owned_test"},
    ) == tuple(tables)


def test_schema_evidence_rejects_a_different_database(monkeypatch):
    checker = load(
        monkeypatch, json.dumps({"database": "other_test", "public_tables": []})
    )
    with pytest.raises(checker.ImageCheckError, match="unexpected database"):
        checker.verify_container_database_connection(
            "owned-container",
            {"DATABASE_URL": "postgresql+asyncpg://example.invalid/owned_test"},
        )


def test_invalid_evidence_does_not_echo_untrusted_output(monkeypatch):
    checker = load(monkeypatch, "private-output-marker")
    with pytest.raises(checker.ImageCheckError) as failure:
        checker.verify_container_database_connection(
            "owned-container",
            {"DATABASE_URL": "postgresql+asyncpg://example.invalid/owned_test"},
        )
    assert "private-output-marker" not in str(failure.value)
