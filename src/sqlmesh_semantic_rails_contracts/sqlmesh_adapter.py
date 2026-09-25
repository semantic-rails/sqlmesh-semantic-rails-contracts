"""SQLMesh project metadata adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._contracts import ResourceSnapshot


def load_sqlmesh_snapshots(project_dir: Path, gateway: str | None = None) -> dict[str, ResourceSnapshot]:
    try:
        from sqlmesh import Context
        from sqlmesh.core.model.definition import ExternalModel
    except ModuleNotFoundError as exc:
        raise RuntimeError("SQLMesh is required. Install this package with its default dependencies.") from exc

    context = Context(paths=str(project_dir), gateway=gateway)
    selected_gateway = getattr(context, "selected_gateway", None) or getattr(context, "gateway", None) or gateway
    default_dialect = getattr(context, "default_dialect", None)
    models = getattr(context, "models", {})
    out: dict[str, ResourceSnapshot] = {}
    for name, model in dict(models).items():
        snapshot = snapshot_from_model(str(name), model, selected_gateway, default_dialect, ExternalModel)
        for alias in model_aliases(str(name), model, snapshot):
            out.setdefault(alias, snapshot)
    return out


def model_aliases(key: str, model: Any, snapshot: ResourceSnapshot) -> set[str]:
    aliases = {key, snapshot.name, unquote_identifier(key), unquote_identifier(snapshot.name)}
    logical_name = getattr(model, "name", None)
    if logical_name:
        aliases.add(str(logical_name))
        aliases.add(unquote_identifier(str(logical_name)))
    return {alias for alias in aliases if alias}


def unquote_identifier(value: str) -> str:
    return value.replace('"', "").replace("`", "").replace("[", "").replace("]", "")


def snapshot_from_model(
    name: str,
    model: Any,
    gateway: str | None,
    default_dialect: str | None,
    external_model_type: type[Any],
) -> ResourceSnapshot:
    dialect = getattr(model, "dialect", None) or default_dialect
    columns = normalize_columns(
        getattr(model, "columns_to_types", None) or getattr(model, "columns", None) or {},
        dialect,
    )
    fqn = str(getattr(model, "fqn", None) or getattr(model, "name", None) or name)
    parts = fqn.split(".")
    catalog = unquote_identifier(parts[-3]) if len(parts) >= 3 else None
    schema = unquote_identifier(parts[-2]) if len(parts) >= 2 else None
    identifier = unquote_identifier(parts[-1]) if parts else unquote_identifier(fqn)
    relation_name = ".".join(part for part in (catalog, schema, identifier) if part)
    audits = audit_names(getattr(model, "audits", None))
    tags = {str(tag) for tag in (getattr(model, "tags", None) or [])}
    kind = getattr(model, "kind", None)
    raw_kind_name = getattr(kind, "name", None) or getattr(kind, "kind", None) or str(kind or "")
    kind_name = getattr(raw_kind_name, "value", None) or str(raw_kind_name or "")
    project = getattr(model, "project", None)
    owner = getattr(model, "owner", None)
    model_gateway = getattr(model, "gateway", None) or gateway
    is_external = isinstance(model, external_model_type) or bool(getattr(kind, "is_external", False))
    return ResourceSnapshot(
        name=fqn,
        columns=columns,
        catalog=catalog,
        schema=schema,
        identifier=identifier,
        relation_name=relation_name,
        project=str(project) if project else None,
        gateway=str(model_gateway) if model_gateway else None,
        kind=str(kind_name).upper() if kind_name else None,
        owner=str(owner) if owner else None,
        tags=tags,
        audits=audits,
        is_external=is_external,
    )


def normalize_columns(raw_columns: Any, dialect: str | None) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_columns, Mapping):
        for name, value in raw_columns.items():
            out[str(name).lower()] = {"name": str(name), "data_type": column_type(value, dialect)}
    return out


def column_type(value: Any, dialect: str | None) -> str:
    if hasattr(value, "sql"):
        try:
            return str(value.sql(dialect=dialect or ""))
        except TypeError:
            return str(value.sql())
    return str(value)


def audit_names(raw_audits: Any) -> set[str]:
    names: set[str] = set()
    for audit in raw_audits or []:
        if isinstance(audit, tuple) and audit:
            names.add(str(audit[0]))
        elif hasattr(audit, "name"):
            names.add(str(audit.name))
        else:
            text = str(audit)
            if text:
                names.add(text)
    return names
