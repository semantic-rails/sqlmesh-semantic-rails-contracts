"""Compose a SQLMesh binding with the engine-owned semantic contract."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from semantic_rails_contracts_core.exporter import (
    export_semantic_contract,
    parse_model_map,
)

from . import __version__


def _binding_resource(
    semantic_resource: Mapping[str, Any],
    *,
    args: Namespace,
    model_map: Mapping[str, str],
) -> dict[str, Any]:
    model_id = str(semantic_resource.get("semantic_model_id") or "")
    sqlmesh_model = model_map.get(
        model_id,
        f"{args.sqlmesh_model_prefix}{model_id}{args.sqlmesh_model_suffix}",
    )
    row: dict[str, Any] = {
        "semantic_model_id": model_id,
        "sqlmesh_model": sqlmesh_model,
        "allow_extra_columns": args.allow_extra_columns,
    }
    for output_key, arg_value in {
        "sqlmesh_project": args.sqlmesh_project,
        "sqlmesh_gateway": args.sqlmesh_gateway,
        "sqlmesh_kind": args.sqlmesh_kind,
        "owner": args.owner,
        "sqlmesh_catalog": args.sqlmesh_catalog,
        "sqlmesh_schema": args.sqlmesh_schema,
        "sqlmesh_identifier": args.sqlmesh_identifier,
        "sqlmesh_relation_name": args.sqlmesh_relation_name,
    }.items():
        if arg_value is not None:
            row[output_key] = arg_value
    if args.tag:
        row["tags"] = list(args.tag)
    if args.audit:
        row["audits"] = list(args.audit)
    return row


def build_sqlmesh_contract(args: Namespace) -> dict[str, Any]:
    root = Path(args.semantic_package).resolve()
    contract = export_semantic_contract(root)
    semantic = deepcopy(dict(contract["semantic"]))
    semantic_packages = semantic.get("packages")
    if not isinstance(semantic_packages, list) or not semantic_packages:
        raise RuntimeError("Semantic Rails contract producer returned no semantic packages.")

    model_map = parse_model_map(args.model_map or [])
    include = set(args.include_model or [])
    seen_models: set[str] = set()
    binding_packages: list[dict[str, Any]] = []

    for semantic_package in semantic_packages:
        if not isinstance(semantic_package, dict):
            raise RuntimeError("Semantic Rails contract producer returned an invalid package row.")
        package_id = str(semantic_package.get("package_id") or "")
        resources = semantic_package.get("resources")
        if not isinstance(resources, list):
            raise RuntimeError(f"Semantic Rails package {package_id or '<unknown>'} returned invalid resources.")
        selected_resources: list[dict[str, Any]] = []
        binding_resources: list[dict[str, Any]] = []
        for raw_resource in resources:
            if not isinstance(raw_resource, Mapping):
                raise RuntimeError(f"Semantic Rails package {package_id or '<unknown>'} returned an invalid resource.")
            model_id = str(raw_resource.get("semantic_model_id") or "")
            if not model_id:
                raise RuntimeError("Semantic Rails semantic resource is missing semantic_model_id.")
            if include and model_id not in include:
                continue
            seen_models.add(model_id)
            selected_resources.append(deepcopy(dict(raw_resource)))
            binding_resources.append(_binding_resource(raw_resource, args=args, model_map=model_map))
        semantic_package["resources"] = selected_resources
        digest = str(semantic_package.get("semantic_hash") or "")
        binding_packages.append(
            {
                "package_id": package_id,
                "accepted_semantic_hashes": [digest] if digest else [],
                "policy": {
                    "severity": "warning" if args.severity == "warn" else args.severity,
                    "type_check": args.type_check,
                    "allow_extra_columns": args.allow_extra_columns,
                    "require_owner": args.require_owner,
                    "require_audits": args.require_audits,
                },
                "resources": binding_resources,
            }
        )

    unknown_mappings = sorted(set(model_map) - seen_models)
    if unknown_mappings:
        raise ValueError("Model mappings did not match exported semantic resources: " + ", ".join(unknown_mappings))
    missing_includes = sorted(include - seen_models)
    if missing_includes:
        raise ValueError("Included models were not found in the semantic contract: " + ", ".join(missing_includes))

    contract["semantic"] = semantic
    contract["binding"] = {
        "kind": "sqlmesh",
        "binding_version": 1,
        "producer": {
            "name": "sqlmesh-semantic-rails-contracts",
            "version": __version__,
        },
        "packages": binding_packages,
    }
    return {"semantic_rails_contracts": contract}
