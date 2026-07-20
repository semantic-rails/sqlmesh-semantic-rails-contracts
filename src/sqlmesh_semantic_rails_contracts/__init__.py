"""SQLMesh integration for Semantic Rails contract checks."""

import json
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from typing import Any

SCHEMA_NAMES = (
    "semantic_contract.v1.json",
    "sqlmesh_binding.v1.json",
    "sqlmesh_contract.v1.json",
    "sqlmesh_validation_report.v1.json",
    "validation_report.v1.json",
)

__all__ = ["SCHEMA_NAMES", "__version__", "load_schema"]

try:
    __version__ = version("sqlmesh-semantic-rails-contracts")
except PackageNotFoundError:  # source checkout without an editable install
    __version__ = "0.0.0+unknown"


def load_schema(name: str) -> dict[str, Any]:
    """Load a packaged canonical or SQLMesh-owned schema by stable filename."""

    if name not in SCHEMA_NAMES:
        raise ValueError(f"Unknown SQLMesh Semantic Rails schema {name!r}")
    resource = files(__package__).joinpath("schemas", name)
    try:
        text = resource.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = (Path(__file__).resolve().parents[2] / "schemas" / name).read_text(encoding="utf-8")
    return dict(json.loads(text))
