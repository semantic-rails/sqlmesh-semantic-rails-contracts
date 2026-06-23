"""SQLMesh contract exporter for Semantic Rails YAML packages."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from semantic_rails_contracts_core.exporter import (
    collect_entities,
    collect_package_meta,
    iter_model_payloads,
    load_package_documents,
    model_required_columns,
    package_hash,
    parse_model_map,
)


def build_sqlmesh_contract(args: Namespace) -> dict[str, Any]:
    root = Path(args.semantic_package).resolve()
    docs = load_package_documents(root)
    meta = collect_package_meta(docs)
    entities = collect_entities(docs)
    model_map = parse_model_map(args.model_map or [])
    include = set(args.include_model or [])

    models: list[dict[str, Any]] = []
    for model in iter_model_payloads(docs):
        model_id = str(model.get("id") or model.get("name") or "")
        if include and model_id not in include:
            continue
        sqlmesh_model = model_map.get(model_id, f"{args.sqlmesh_model_prefix}{model_id}{args.sqlmesh_model_suffix}")
        row: dict[str, Any] = {
            "semantic_model_id": model_id,
            "semantic_relation": model.get("relation"),
            "sqlmesh_model": sqlmesh_model,
            "allow_extra_columns": args.allow_extra_columns,
            "columns": model_required_columns(model, entities),
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
            row["tags"] = args.tag
        if args.audit:
            row["audits"] = args.audit
        models.append(row)

    digest = package_hash(root)
    return {
        "semantic_rails_contracts": {
            "packages": [
                {
                    **meta,
                    "contract_version": 1,
                    "semantic_hash": digest,
                    "accepted_semantic_hashes": [digest],
                    "policy": {
                        "severity": args.severity,
                        "type_check": args.type_check,
                        "allow_extra_columns": args.allow_extra_columns,
                        "require_owner": args.require_owner,
                        "require_audits": args.require_audits,
                    },
                    "models": models,
                }
            ]
        }
    }
