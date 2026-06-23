"""Framework-neutral contract parsing and validation primitives."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TYPE_ALIASES = {
    "string": {"string", "varchar", "text", "character varying"},
    "varchar": {"string", "varchar", "text", "character varying"},
    "text": {"string", "varchar", "text", "character varying"},
    "integer": {"int", "integer", "bigint", "number", "numeric", "int64"},
    "int": {"int", "integer", "bigint", "number", "numeric", "int64"},
    "bigint": {"int", "integer", "bigint", "number", "numeric", "int64"},
    "int64": {"int", "integer", "bigint", "number", "numeric", "int64"},
    "numeric": {"numeric", "number", "decimal", "double", "float", "real", "bignumeric"},
    "number": {"numeric", "number", "decimal", "double", "float", "real", "bignumeric"},
    "double": {"numeric", "number", "decimal", "double", "float", "real", "bignumeric"},
    "boolean": {"boolean", "bool"},
    "bool": {"boolean", "bool"},
    "timestamp": {"timestamp", "timestamp_ntz", "timestamp_tz", "datetime"},
    "datetime": {"timestamp", "timestamp_ntz", "timestamp_tz", "datetime"},
    "date": {"date"},
}


@dataclass(frozen=True)
class ContractIssue:
    code: str
    severity: str
    package_id: str
    model: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "package_id": self.package_id,
            "model": self.model,
            "message": self.message,
        }


@dataclass(frozen=True)
class ContractPolicy:
    severity: str = "error"
    type_check: str = "ignore"
    allow_extra_columns: bool = True
    require_owner: bool = False
    require_audits: bool = False


@dataclass(frozen=True)
class ContractResource:
    package_id: str
    semantic_model_id: str
    raw: Mapping[str, Any]
    policy: ContractPolicy

    @property
    def severity(self) -> str:
        return str(self.raw.get("severity") or self.policy.severity)

    @property
    def target_name(self) -> str:
        return str(
            self.raw.get("sqlmesh_model")
            or self.raw.get("sqlmesh_name")
            or self.raw.get("model")
            or self.raw.get("dbt_model")
            or self.raw.get("dbt_name")
            or self.semantic_model_id
        )

    @property
    def columns(self) -> list[dict[str, Any]]:
        return expected_columns(self.raw.get("columns", []))

    @property
    def allow_extra_columns(self) -> bool:
        return bool_value(self.raw.get("allow_extra_columns", self.policy.allow_extra_columns))

    @property
    def type_check(self) -> str:
        return str(self.raw.get("type_check") or self.policy.type_check)


@dataclass(frozen=True)
class ResourceSnapshot:
    name: str
    columns: Mapping[str, Mapping[str, Any]]
    catalog: str | None = None
    schema: str | None = None
    identifier: str | None = None
    relation_name: str | None = None
    project: str | None = None
    gateway: str | None = None
    kind: str | None = None
    owner: str | None = None
    tags: set[str] = field(default_factory=set)
    audits: set[str] = field(default_factory=set)
    is_external: bool = False


def load_contract_file(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    nested = payload.get("semantic_rails_contracts")
    if nested is not None:
        if not isinstance(nested, dict):
            raise ValueError("semantic_rails_contracts must be a mapping")
        return nested
    return payload


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def packages(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    package_rows = spec.get("packages")
    if isinstance(package_rows, list):
        return [row for row in package_rows if isinstance(row, Mapping)]
    if spec.get("models") or spec.get("resources"):
        return [spec]
    return []


def _entries(package_contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for key in ("resources", "models"):
        rows = package_contract.get(key, [])
        if isinstance(rows, Mapping):
            for semantic_model_id, payload in rows.items():
                row = dict(payload or {})
                row.setdefault("semantic_model_id", semantic_model_id)
                out.append(row)
        elif isinstance(rows, list):
            out.extend(row for row in rows if isinstance(row, Mapping))
    return out


def contract_summary(spec: Mapping[str, Any]) -> dict[str, int]:
    package_rows = packages(spec)
    resource_count = sum(len(_entries(row)) for row in package_rows)
    return {"package_count": len(package_rows), "resource_count": resource_count}


def contract_resources(spec: Mapping[str, Any]) -> tuple[list[ContractIssue], list[ContractResource]]:
    issues: list[ContractIssue] = []
    resources: list[ContractResource] = []
    if not isinstance(spec, Mapping) or not spec:
        return [
            ContractIssue(
                "INVALID_CONTRACT",
                "error",
                "",
                "",
                "semantic_rails_contracts must be a non-empty mapping.",
            )
        ], []

    package_rows = packages(spec)
    if not package_rows:
        return [
            ContractIssue(
                "INVALID_CONTRACT",
                "error",
                "",
                "",
                "No Semantic Rails packages were declared. Use packages: [...] or a single package payload.",
            )
        ], []

    for package_contract in package_rows:
        package_id = str(
            package_contract.get("package_id")
            or package_contract.get("id")
            or package_contract.get("name")
            or ""
        )
        policy_payload = package_contract.get("policy") if isinstance(package_contract.get("policy"), Mapping) else {}
        policy = ContractPolicy(
            severity=str(policy_payload.get("severity", "error")),
            type_check=str(policy_payload.get("type_check", "ignore")),
            allow_extra_columns=bool_value(policy_payload.get("allow_extra_columns", True)),
            require_owner=bool_value(policy_payload.get("require_owner", False)),
            require_audits=bool_value(policy_payload.get("require_audits", False)),
        )
        semantic_hash = package_contract.get("semantic_hash")
        accepted_hashes = as_list(package_contract.get("accepted_semantic_hashes"))
        if accepted_hashes and semantic_hash not in accepted_hashes:
            issues.append(
                ContractIssue(
                    "SEMANTIC_HASH_NOT_ACCEPTED",
                    policy.severity,
                    package_id,
                    "",
                    f"Semantic Rails package hash {semantic_hash} is not in accepted_semantic_hashes.",
                )
            )

        entries = _entries(package_contract)
        if not entries:
            issues.append(
                ContractIssue(
                    "INVALID_CONTRACT",
                    policy.severity,
                    package_id,
                    "",
                    "Package declares no resource contracts. Use models: or resources:.",
                )
            )
        for row in entries:
            semantic_model_id = str(row.get("semantic_model_id") or row.get("id") or row.get("name") or "")
            if not semantic_model_id:
                issues.append(
                    ContractIssue(
                        "INVALID_MODEL_CONTRACT",
                        policy.severity,
                        package_id,
                        "",
                        "Every resource contract must include semantic_model_id, id, or name.",
                    )
                )
                continue
            resources.append(ContractResource(package_id, semantic_model_id, row, policy))
    return issues, resources


def expected_columns(columns: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(columns, Mapping):
        for name, payload in columns.items():
            row = dict(payload or {})
            row.setdefault("name", name)
            out.append(row)
    elif isinstance(columns, list):
        for column in columns:
            if isinstance(column, str):
                out.append({"name": column})
            elif isinstance(column, Mapping) and column.get("name"):
                out.append(dict(column))
    return out


def columns_by_name(columns: Mapping[str, Mapping[str, Any]] | list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    if isinstance(columns, Mapping):
        for name, payload in columns.items():
            row = dict(payload or {})
            row.setdefault("name", name)
            out[str(name).lower()] = row
    elif isinstance(columns, list):
        for column in columns:
            if isinstance(column, Mapping) and column.get("name"):
                out[str(column["name"]).lower()] = column
    return out


def types_match(expected_type: str | None, actual_type: str | None, mode: str) -> bool:
    if mode == "exact":
        return normalize_exact_type(expected_type) == normalize_exact_type(actual_type)
    expected = normalize_compatible_type(expected_type)
    actual = normalize_compatible_type(actual_type)
    expected_group = TYPE_ALIASES.get(expected, {expected})
    return actual in expected_group


def normalize_exact_type(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().strip())


def normalize_compatible_type(value: str | None) -> str:
    normalized = normalize_exact_type(value)
    normalized = re.sub(r"\([^)]*\)", "", normalized).strip()
    normalized = normalized.replace("character varying", "varchar")
    if normalized in {"timestamp with time zone", "timestamp without time zone", "timestamptz"}:
        return "timestamp"
    if normalized.startswith("timestamp"):
        return "timestamp"
    if normalized.startswith("datetime"):
        return "datetime"
    if normalized.startswith(("decimal", "numeric", "number")):
        return "numeric"
    if normalized.startswith(("varchar", "string", "text")):
        return "varchar"
    if normalized.startswith(("bigint", "integer", "int64", "int")):
        return "integer"
    if normalized.startswith(("bool", "boolean")):
        return "boolean"
    return normalized


def collect_contract_issues(
    spec: Mapping[str, Any],
    snapshots: Mapping[str, ResourceSnapshot],
    *,
    framework: str,
    not_found_code: str,
    ambiguous_code: str,
) -> list[ContractIssue]:
    issues, resources = contract_resources(spec)
    for resource in resources:
        issues.extend(validate_resource(resource, snapshots, framework, not_found_code, ambiguous_code))
    return issues


def validate_resource(
    resource: ContractResource,
    snapshots: Mapping[str, ResourceSnapshot],
    framework: str,
    not_found_code: str,
    ambiguous_code: str,
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    target_name = resource.target_name
    candidates = unique_snapshots(
        snapshot for key, snapshot in snapshots.items() if relation_name_matches(key, target_name)
    )
    candidates = disambiguate_candidates(resource, candidates)
    if not candidates:
        return [
            ContractIssue(
                not_found_code,
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                f"Expected {framework} model {resource.target_name} was not found.",
            )
        ]
    if len(candidates) > 1:
        return [
            ContractIssue(
                ambiguous_code,
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                f"Expected {framework} model {resource.target_name} matched multiple models. "
                "Use a fully qualified name.",
            )
        ]
    snapshot = candidates[0]
    issues.extend(validate_metadata(resource, snapshot, framework))
    issues.extend(validate_columns(resource, snapshot, framework))
    return issues


def relation_name_matches(candidate: str, target: str) -> bool:
    normalized_candidate = normalize_relation_token(candidate)
    normalized_target = normalize_relation_token(target)
    return normalized_candidate == normalized_target or normalized_candidate.endswith(f".{normalized_target}")


def normalize_relation_token(value: str) -> str:
    return value.replace('"', "").replace("`", "").replace("[", "").replace("]", "").lower()


def disambiguate_candidates(
    resource: ContractResource,
    candidates: list[ResourceSnapshot],
) -> list[ResourceSnapshot]:
    remaining = candidates
    for field_name, keys in {
        "project": ("sqlmesh_project", "project"),
        "gateway": ("sqlmesh_gateway", "gateway"),
        "catalog": ("sqlmesh_catalog", "catalog", "database"),
        "schema": ("sqlmesh_schema", "schema"),
        "identifier": ("sqlmesh_identifier", "identifier"),
        "relation_name": ("sqlmesh_relation_name", "relation_name"),
    }.items():
        expected = first_present(resource.raw, keys)
        if expected is None:
            continue
        filtered = [
            snapshot
            for snapshot in remaining
            if metadata_values_match(field_name, expected, getattr(snapshot, field_name))
        ]
        if filtered:
            remaining = filtered
    return remaining


def unique_snapshots(snapshots: Iterable[ResourceSnapshot]) -> list[ResourceSnapshot]:
    out: list[ResourceSnapshot] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for snapshot in snapshots:
        key = (snapshot.name, snapshot.project, snapshot.gateway)
        if key not in seen:
            seen.add(key)
            out.append(snapshot)
    return out


def validate_metadata(resource: ContractResource, snapshot: ResourceSnapshot, framework: str) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    pairs = {
        "project": ("sqlmesh_project", "project"),
        "gateway": ("sqlmesh_gateway", "gateway"),
        "kind": ("sqlmesh_kind", "kind"),
        "owner": ("owner",),
        "catalog": ("sqlmesh_catalog", "catalog", "database"),
        "schema": ("sqlmesh_schema", "schema"),
        "identifier": ("sqlmesh_identifier", "identifier"),
        "relation_name": ("sqlmesh_relation_name", "relation_name"),
        "is_external": ("sqlmesh_external", "external"),
    }
    for field_name, keys in pairs.items():
        expected = first_present(resource.raw, keys)
        actual = getattr(snapshot, field_name)
        if expected is not None and not metadata_values_match(field_name, expected, actual):
            issues.append(
                ContractIssue(
                    metadata_issue_code(field_name),
                    resource.severity,
                    resource.package_id,
                    resource.semantic_model_id,
                    f"Expected {framework} {field_name} {expected}, found {actual}.",
                )
            )

    expected_tags = {str(value) for value in as_list(resource.raw.get("tags") or resource.raw.get("sqlmesh_tags"))}
    for tag in sorted(expected_tags - snapshot.tags):
        issues.append(
            ContractIssue(
                "SQLMESH_TAG_MISSING",
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                f"Expected {framework} tag {tag} is missing.",
            )
        )

    expected_audits = {
        str(value) for value in as_list(resource.raw.get("audits") or resource.raw.get("sqlmesh_audits"))
    }
    if resource.policy.require_audits and not expected_audits and not snapshot.audits:
        issues.append(
            ContractIssue(
                "SQLMESH_AUDIT_MISSING",
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                "Expected at least one SQLMesh audit, found none.",
            )
        )
    for audit in sorted(expected_audits - snapshot.audits):
        issues.append(
            ContractIssue(
                "SQLMESH_AUDIT_MISSING",
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                f"Expected {framework} audit {audit} is missing.",
            )
        )

    if resource.policy.require_owner and not snapshot.owner:
        issues.append(
            ContractIssue(
                "SQLMESH_OWNER_MISSING",
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                "Expected SQLMesh owner metadata, found none.",
            )
        )
    return issues


def metadata_values_match(field_name: str, expected: Any, actual: Any) -> bool:
    if field_name == "is_external":
        return bool_value(expected) == bool(actual)
    if field_name == "kind":
        return str(actual or "").upper() == str(expected or "").upper()
    if field_name in {"catalog", "schema", "identifier", "relation_name"}:
        return normalize_relation_token(str(actual or "")) == normalize_relation_token(str(expected or ""))
    return str(actual or "") == str(expected)


def metadata_issue_code(field_name: str) -> str:
    if field_name in {"catalog", "schema", "identifier", "relation_name"}:
        return "SQLMESH_RELATION_MISMATCH"
    if field_name == "is_external":
        return "SQLMESH_EXTERNAL_MISMATCH"
    return f"SQLMESH_{field_name.upper()}_MISMATCH"


def validate_columns(resource: ContractResource, snapshot: ResourceSnapshot, framework: str) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    actual_columns = columns_by_name(snapshot.columns)
    expected = resource.columns
    for column in expected:
        name = column.get("name")
        if not name:
            issues.append(
                ContractIssue(
                    "INVALID_MODEL_CONTRACT",
                    resource.severity,
                    resource.package_id,
                    resource.semantic_model_id,
                    "Every expected column entry must include name.",
                )
            )
            continue
        key = str(name).lower()
        if key not in actual_columns:
            reasons = ", ".join(str(value) for value in as_list(column.get("required_by")))
            detail = f"Missing {framework} column {name} required by Semantic Rails model {resource.semantic_model_id}"
            if reasons:
                detail += f" ({reasons})"
            issues.append(
                ContractIssue(
                    "SQLMESH_COLUMN_MISSING",
                    resource.severity,
                    resource.package_id,
                    resource.semantic_model_id,
                    detail + ".",
                )
            )
        elif resource.type_check != "ignore" and column.get("data_type"):
            actual_type = actual_columns[key].get("data_type") or actual_columns[key].get("type")
            if not types_match(str(column.get("data_type")), str(actual_type or ""), resource.type_check):
                issues.append(
                    ContractIssue(
                        "SQLMESH_COLUMN_TYPE_MISMATCH",
                        resource.severity,
                        resource.package_id,
                        resource.semantic_model_id,
                        f"Column {name} expected type {column.get('data_type')}, found {actual_type}.",
                    )
                )

    if not resource.allow_extra_columns:
        expected_names = {str(column.get("name")).lower() for column in expected if column.get("name")}
        for actual_name in actual_columns:
            if actual_name not in expected_names:
                issues.append(
                    ContractIssue(
                        "SQLMESH_COLUMN_EXTRA",
                        resource.severity,
                        resource.package_id,
                        resource.semantic_model_id,
                        f"{framework} column {actual_name} is not listed in the Semantic Rails contract "
                        "and allow_extra_columns is false.",
                    )
                )
    return issues


def first_present(payload: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None
