from __future__ import annotations

import json
from pathlib import Path

from scripts.check_schema_compatibility import compare_directories
from scripts.verify_published_artifacts import compare_release


def _write_schema(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_schema_compatibility_allows_additive_closed_object_changes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    name = "binding.v1.json"
    original = {
        "$id": "https://semantic-rails.com/schemas/binding.v1.json",
        "type": "object",
        "additionalProperties": False,
        "properties": {"mode": {"enum": ["error"]}},
    }
    additive = {
        **original,
        "properties": {
            "mode": {"enum": ["error", "warning"]},
            "owner": {"type": "string"},
        },
    }
    _write_schema(baseline / name, original)
    _write_schema(current / name, additive)

    report = compare_directories(baseline, current, [name])

    assert report["ok"] is True
    assert report["summary"] == {"breaking": 0, "additive": 2}


def test_schema_compatibility_rejects_required_and_identity_changes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    name = "binding.v1.json"
    _write_schema(
        baseline / name,
        {
            "$id": "https://semantic-rails.com/schemas/binding.v1.json",
            "type": "object",
            "properties": {"owner": {"type": "string"}},
        },
    )
    _write_schema(
        current / name,
        {
            "$id": "https://example.invalid/binding.v1.json",
            "type": "object",
            "required": ["owner"],
            "properties": {"owner": {"type": "string"}},
        },
    )

    report = compare_directories(baseline, current, [name])

    assert report["ok"] is False
    assert {row["kind"] for row in report["breaking_changes"]} == {
        "$id_changed",
        "required_added",
    }


def test_pypi_comparison_requires_exact_filenames_and_hashes() -> None:
    expected = {"adapter.whl": "abc", "adapter.tar.gz": "def"}
    exact = {
        "urls": [
            {"filename": "adapter.whl", "digests": {"sha256": "abc"}},
            {"filename": "adapter.tar.gz", "digests": {"sha256": "def"}},
        ]
    }
    wrong = {
        "urls": [
            {"filename": "adapter.whl", "digests": {"sha256": "changed"}},
            {"filename": "adapter.tar.gz", "digests": {"sha256": "def"}},
        ]
    }

    assert compare_release(expected, exact) == (True, "")
    assert compare_release(expected, wrong) == (
        False,
        "Published SHA-256 mismatch for adapter.whl.",
    )
