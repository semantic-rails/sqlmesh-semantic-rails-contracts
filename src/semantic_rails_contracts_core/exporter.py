"""Adapter-side access to the canonical Semantic Rails contract producer.

Contract validation remains standalone and SQLMesh-native. Export is different:
only the engine owns package parsing and semantic fingerprints, so this module
deliberately has no raw-YAML fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any


class SemanticRailsProducerUnavailable(RuntimeError):
    """Raised when the optional engine export surface is not installed."""


def export_semantic_contract(package_path: str | Path) -> dict[str, Any]:
    try:
        from semantic_rails.contracts import export_semantic_contract as engine_export
    except (ImportError, ModuleNotFoundError) as exc:
        raise SemanticRailsProducerUnavailable(
            "Contract export requires Semantic Rails 0.2 or newer. "
            "Install sqlmesh-semantic-rails-contracts[export], or generate the "
            "neutral semantic contract with the semantic-rails CLI."
        ) from exc

    payload = engine_export(Path(package_path).expanduser().resolve())
    if not isinstance(payload, Mapping):
        raise RuntimeError("Semantic Rails contract producer returned a non-mapping payload.")
    root = payload.get("semantic_rails_contracts", payload)
    if not isinstance(root, Mapping):
        raise RuntimeError("Semantic Rails contract producer returned an invalid root payload.")
    out = deepcopy(dict(root))
    if out.get("contract_format_version") != 1 or not isinstance(out.get("semantic"), Mapping):
        raise RuntimeError(
            "Semantic Rails contract producer returned an unsupported contract format; "
            "expected contract_format_version 1."
        )
    return out


def parse_model_map(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values:
        left, sep, right = value.partition("=")
        if not sep or not left.strip() or not right.strip():
            raise ValueError(f"Invalid mapping {value!r}; expected semantic_model=target_model")
        out[left.strip()] = right.strip()
    return out
