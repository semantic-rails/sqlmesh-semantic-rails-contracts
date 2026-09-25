"""SQLMesh-owned contract parsing, binding validation, and resource checks."""

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

CONTRACT_FORMAT_VERSION = 1
BINDING_VERSION = 1
REPORT_FORMAT_VERSION = 1
SQLMESH_BINDING_KIND = "sqlmesh"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_TOP_LEVEL_FIELDS = {"contract_format_version", "semantic", "binding"}
_SEMANTIC_FIELDS = {"producer", "packages"}
_PRODUCER_FIELDS = {"name", "version"}
_SEMANTIC_PACKAGE_FIELDS = {
    "package_id",
    "namespace",
    "package_schema_version",
    "semantic_hash",
    "resources",
}
_SEMANTIC_RESOURCE_FIELDS = {"semantic_model_id", "relation", "columns"}
_SEMANTIC_COLUMN_FIELDS = {"name", "data_type", "required_by"}
_BINDING_FIELDS = {"kind", "binding_version", "producer", "packages"}
_BINDING_PACKAGE_FIELDS = {
    "package_id",
    "accepted_semantic_hashes",
    "policy",
    "resources",
}
_POLICY_FIELDS = {
    "severity",
    "type_check",
    "allow_extra_columns",
    "require_owner",
    "require_audits",
}
_BINDING_RESOURCE_FIELDS = {
    "semantic_model_id",
    "sqlmesh_model",
    "sqlmesh_project",
    "sqlmesh_gateway",
    "sqlmesh_kind",
    "sqlmesh_external",
    "owner",
    "tags",
    "audits",
    "sqlmesh_catalog",
    "sqlmesh_schema",
    "sqlmesh_identifier",
    "sqlmesh_relation_name",
    "severity",
    "type_check",
    "allow_extra_columns",
}


@dataclass(frozen=True)
class ContractIssue:
    code: str
    severity: str
    package_id: str
    semantic_model_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": normalize_severity(self.severity),
            "package_id": self.package_id,
            "semantic_model_id": self.semantic_model_id,
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
        return normalize_severity(self.raw.get("severity") or self.policy.severity)

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
    if "semantic_rails_contracts" in payload:
        nested = payload["semantic_rails_contracts"]
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


def normalize_severity(value: Any) -> str:
    """Normalize legacy ``warn`` values to the public report vocabulary."""

    return "warning" if str(value or "").lower() in {"warn", "warning"} else "error"


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


def contract_metadata(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the independently versioned wire-contract identities."""

    if "contract_format_version" not in spec:
        return {
            "contract_format_version": 0,
            "binding_kind": None,
            "binding_version": None,
            "legacy": True,
        }
    binding = spec.get("binding")
    binding_payload = binding if isinstance(binding, Mapping) else {}
    raw_contract_version = spec.get("contract_format_version")
    raw_binding_version = binding_payload.get("binding_version")
    raw_binding_kind = binding_payload.get("kind")
    return {
        "contract_format_version": (
            raw_contract_version
            if isinstance(raw_contract_version, int) and not isinstance(raw_contract_version, bool)
            else None
        ),
        "binding_kind": raw_binding_kind if isinstance(raw_binding_kind, str) else None,
        "binding_version": (
            raw_binding_version
            if isinstance(raw_binding_version, int) and not isinstance(raw_binding_version, bool)
            else None
        ),
        "legacy": False,
    }


def _issue(
    code: str,
    message: str,
    *,
    package_id: str = "",
    semantic_model_id: str = "",
) -> ContractIssue:
    return ContractIssue(code, "error", package_id, semantic_model_id, message)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_known_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    *,
    label: str,
    code: str,
    issues: list[ContractIssue],
    package_id: str = "",
    semantic_model_id: str = "",
) -> bool:
    valid = True
    for raw_key in value:
        key = str(raw_key)
        if key not in allowed:
            issues.append(
                _issue(
                    code,
                    f"Unsupported {label} field {key}.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            valid = False
    return valid


def _validate_string_list(
    value: Any,
    *,
    field_name: str,
    code: str,
    issues: list[ContractIssue],
    package_id: str,
    semantic_model_id: str = "",
) -> bool:
    if not isinstance(value, list):
        issues.append(
            _issue(
                code,
                f"{field_name} must be a list.",
                package_id=package_id,
                semantic_model_id=semantic_model_id,
            )
        )
        return False
    valid = True
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not _is_nonempty_string(item):
            issues.append(
                _issue(
                    code,
                    f"{field_name}[{index}] must be a non-empty string.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            valid = False
            continue
        normalized = str(item)
        if normalized in seen:
            issues.append(
                _issue(
                    code,
                    f"{field_name} must not contain duplicate values.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            valid = False
        seen.add(normalized)
    return valid


def _validate_producer(
    value: Any,
    *,
    expected_name: str,
    field_name: str,
    required: bool,
    issues: list[ContractIssue],
) -> bool:
    if value is None and not required:
        return True
    if not isinstance(value, Mapping):
        issues.append(_issue("INVALID_CONTRACT", f"{field_name} must be a mapping with name and version."))
        return False
    valid = _validate_known_fields(
        value,
        _PRODUCER_FIELDS,
        label=field_name,
        code="INVALID_CONTRACT",
        issues=issues,
    )
    if value.get("name") != expected_name:
        issues.append(_issue("INVALID_CONTRACT", f"{field_name}.name must be {expected_name}."))
        valid = False
    if not _is_nonempty_string(value.get("version")):
        issues.append(_issue("INVALID_CONTRACT", f"{field_name}.version must be a non-empty string."))
        valid = False
    return valid


def _semantic_resource_rows(
    value: Any,
    *,
    package_id: str,
    issues: list[ContractIssue],
) -> tuple[dict[str, dict[str, Any]], bool]:
    if not isinstance(value, list):
        issues.append(
            _issue(
                "INVALID_SEMANTIC_PACKAGE",
                "semantic package resources must be a list.",
                package_id=package_id,
            )
        )
        return {}, False

    rows: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    valid = True
    for index, raw_row in enumerate(value):
        if not isinstance(raw_row, Mapping):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_RESOURCE",
                    f"semantic.resources[{index}] must be a mapping.",
                    package_id=package_id,
                )
            )
            valid = False
            continue
        row = dict(raw_row)
        semantic_model_id = str(row.get("semantic_model_id") or "").strip()
        row_valid = _validate_known_fields(
            row,
            _SEMANTIC_RESOURCE_FIELDS,
            label="semantic resource",
            code="INVALID_SEMANTIC_RESOURCE",
            issues=issues,
            package_id=package_id,
            semantic_model_id=semantic_model_id,
        )
        if not _is_nonempty_string(row.get("semantic_model_id")):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_RESOURCE",
                    "semantic resources must include a non-empty semantic_model_id.",
                    package_id=package_id,
                )
            )
            row_valid = False
        if semantic_model_id and semantic_model_id in seen_ids:
            issues.append(
                _issue(
                    "DUPLICATE_SEMANTIC_RESOURCE",
                    f"semantic_model_id {semantic_model_id} is duplicated in semantic resources.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        if semantic_model_id:
            seen_ids.add(semantic_model_id)
        relation = row.get("relation")
        if "relation" in row and not isinstance(relation, str):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_RESOURCE",
                    "semantic resource relation must be a string when provided.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False

        columns = row.get("columns")
        if not isinstance(columns, list):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_RESOURCE",
                    "semantic resource columns must be a list.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        else:
            for column_index, raw_column in enumerate(columns):
                if not isinstance(raw_column, Mapping):
                    issues.append(
                        _issue(
                            "INVALID_SEMANTIC_COLUMN",
                            f"columns[{column_index}] must be a mapping.",
                            package_id=package_id,
                            semantic_model_id=semantic_model_id,
                        )
                    )
                    row_valid = False
                    continue
                column = dict(raw_column)
                if not _validate_known_fields(
                    column,
                    _SEMANTIC_COLUMN_FIELDS,
                    label="semantic column",
                    code="INVALID_SEMANTIC_COLUMN",
                    issues=issues,
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                ):
                    row_valid = False
                if not _is_nonempty_string(column.get("name")):
                    issues.append(
                        _issue(
                            "INVALID_SEMANTIC_COLUMN",
                            "Every semantic column must include a non-empty name.",
                            package_id=package_id,
                            semantic_model_id=semantic_model_id,
                        )
                    )
                    row_valid = False
                data_type = column.get("data_type")
                if "data_type" in column and not _is_nonempty_string(data_type):
                    issues.append(
                        _issue(
                            "INVALID_SEMANTIC_COLUMN",
                            "Semantic column data_type must be a non-empty string when provided.",
                            package_id=package_id,
                            semantic_model_id=semantic_model_id,
                        )
                    )
                    row_valid = False
                if not _validate_string_list(
                    column.get("required_by"),
                    field_name="semantic column required_by",
                    code="INVALID_SEMANTIC_COLUMN",
                    issues=issues,
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                ):
                    row_valid = False

        if row_valid:
            row["semantic_model_id"] = semantic_model_id
            rows[semantic_model_id] = row
        valid = valid and row_valid
    return rows, valid


def _validate_policy(
    value: Any,
    *,
    package_id: str,
    issues: list[ContractIssue],
) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, Mapping):
        issues.append(
            _issue(
                "INVALID_BINDING_PACKAGE",
                "SQLMesh binding policy must be a mapping.",
                package_id=package_id,
            )
        )
        return {}, False
    policy = dict(value)
    valid = _validate_known_fields(
        policy,
        _POLICY_FIELDS,
        label="SQLMesh policy",
        code="INVALID_BINDING_PACKAGE",
        issues=issues,
        package_id=package_id,
    )
    if "severity" in policy and policy["severity"] not in {"error", "warning"}:
        issues.append(
            _issue(
                "INVALID_BINDING_PACKAGE",
                "SQLMesh policy severity must be error or warning.",
                package_id=package_id,
            )
        )
        valid = False
    if "type_check" in policy and policy["type_check"] not in {"ignore", "compatible", "exact"}:
        issues.append(
            _issue(
                "INVALID_BINDING_PACKAGE",
                "SQLMesh policy type_check must be ignore, compatible, or exact.",
                package_id=package_id,
            )
        )
        valid = False
    for field_name in ("allow_extra_columns", "require_owner", "require_audits"):
        if field_name in policy and not isinstance(policy[field_name], bool):
            issues.append(
                _issue(
                    "INVALID_BINDING_PACKAGE",
                    f"SQLMesh policy {field_name} must be a boolean.",
                    package_id=package_id,
                )
            )
            valid = False
    return policy, valid


def _binding_resource_rows(
    value: Any,
    *,
    package_id: str,
    issues: list[ContractIssue],
) -> tuple[dict[str, dict[str, Any]], bool]:
    if not isinstance(value, list) or not value:
        issues.append(
            _issue(
                "INVALID_BINDING_PACKAGE",
                "SQLMesh binding package resources must be a non-empty list.",
                package_id=package_id,
            )
        )
        return {}, False

    rows: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    valid = True
    string_fields = {
        "sqlmesh_model",
        "sqlmesh_project",
        "sqlmesh_gateway",
        "sqlmesh_kind",
        "owner",
        "sqlmesh_catalog",
        "sqlmesh_schema",
        "sqlmesh_identifier",
        "sqlmesh_relation_name",
    }
    for index, raw_row in enumerate(value):
        if not isinstance(raw_row, Mapping):
            issues.append(
                _issue(
                    "INVALID_BINDING_RESOURCE",
                    f"binding.resources[{index}] must be a mapping.",
                    package_id=package_id,
                )
            )
            valid = False
            continue
        row = dict(raw_row)
        semantic_model_id = str(row.get("semantic_model_id") or "").strip()
        row_valid = _validate_known_fields(
            row,
            _BINDING_RESOURCE_FIELDS,
            label="SQLMesh binding resource",
            code="INVALID_BINDING_RESOURCE",
            issues=issues,
            package_id=package_id,
            semantic_model_id=semantic_model_id,
        )
        if "columns" in row:
            issues.append(
                _issue(
                    "INVALID_MODEL_CONTRACT",
                    "binding resources must not redefine semantic columns.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        if not _is_nonempty_string(row.get("semantic_model_id")):
            issues.append(
                _issue(
                    "INVALID_BINDING_RESOURCE",
                    "SQLMesh binding resources must include a non-empty semantic_model_id.",
                    package_id=package_id,
                )
            )
            row_valid = False
        if semantic_model_id and semantic_model_id in seen_ids:
            issues.append(
                _issue(
                    "DUPLICATE_BINDING_RESOURCE",
                    f"semantic_model_id {semantic_model_id} is duplicated in SQLMesh binding resources.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        if semantic_model_id:
            seen_ids.add(semantic_model_id)
        for field_name in string_fields:
            if field_name == "sqlmesh_model" and not _is_nonempty_string(row.get(field_name)):
                issues.append(
                    _issue(
                        "INVALID_BINDING_RESOURCE",
                        "SQLMesh binding resources must include a non-empty sqlmesh_model.",
                        package_id=package_id,
                        semantic_model_id=semantic_model_id,
                    )
                )
                row_valid = False
            elif field_name in row and not isinstance(row[field_name], str):
                issues.append(
                    _issue(
                        "INVALID_BINDING_RESOURCE",
                        f"{field_name} must be a string.",
                        package_id=package_id,
                        semantic_model_id=semantic_model_id,
                    )
                )
                row_valid = False
        if "sqlmesh_external" in row and not isinstance(row["sqlmesh_external"], bool):
            issues.append(
                _issue(
                    "INVALID_BINDING_RESOURCE",
                    "sqlmesh_external must be a boolean.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        for field_name in ("tags", "audits"):
            if field_name in row and not _validate_string_list(
                row[field_name],
                field_name=field_name,
                code="INVALID_BINDING_RESOURCE",
                issues=issues,
                package_id=package_id,
                semantic_model_id=semantic_model_id,
            ):
                row_valid = False
        if "severity" in row and row["severity"] not in {"error", "warning"}:
            issues.append(
                _issue(
                    "INVALID_BINDING_RESOURCE",
                    "Binding resource severity must be error or warning.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        if "type_check" in row and row["type_check"] not in {"ignore", "compatible", "exact"}:
            issues.append(
                _issue(
                    "INVALID_BINDING_RESOURCE",
                    "Binding resource type_check must be ignore, compatible, or exact.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False
        if "allow_extra_columns" in row and not isinstance(row["allow_extra_columns"], bool):
            issues.append(
                _issue(
                    "INVALID_BINDING_RESOURCE",
                    "Binding resource allow_extra_columns must be a boolean.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
            row_valid = False

        if row_valid:
            row["semantic_model_id"] = semantic_model_id
            rows[semantic_model_id] = row
        valid = valid and row_valid
    return rows, valid


def _v1_packages(spec: Mapping[str, Any]) -> tuple[list[ContractIssue], list[Mapping[str, Any]]]:
    issues: list[ContractIssue] = []
    _validate_known_fields(
        spec,
        _TOP_LEVEL_FIELDS,
        label="top-level composed contract",
        code="INVALID_CONTRACT",
        issues=issues,
    )
    contract_format_version = spec.get("contract_format_version")
    if not _is_integer(contract_format_version) or contract_format_version != CONTRACT_FORMAT_VERSION:
        return [
            *issues,
            _issue(
                "UNSUPPORTED_CONTRACT_FORMAT_VERSION",
                "contract_format_version must be integer 1.",
            ),
        ], []

    semantic = spec.get("semantic")
    binding = spec.get("binding")
    if not isinstance(semantic, Mapping):
        issues.append(_issue("INVALID_CONTRACT", "semantic must be a mapping."))
        return issues, []
    if not isinstance(binding, Mapping):
        issues.append(_issue("INVALID_CONTRACT", "binding must be a mapping."))
        return issues, []
    _validate_known_fields(
        semantic,
        _SEMANTIC_FIELDS,
        label="semantic",
        code="INVALID_CONTRACT",
        issues=issues,
    )
    _validate_producer(
        semantic.get("producer"),
        expected_name="semantic-rails",
        field_name="semantic.producer",
        required=True,
        issues=issues,
    )
    _validate_known_fields(
        binding,
        _BINDING_FIELDS,
        label="SQLMesh binding",
        code="INVALID_CONTRACT",
        issues=issues,
    )
    if "producer" in binding:
        _validate_producer(
            binding.get("producer"),
            expected_name="sqlmesh-semantic-rails-contracts",
            field_name="binding.producer",
            required=True,
            issues=issues,
        )
    if binding.get("kind") != SQLMESH_BINDING_KIND:
        issues.append(
            _issue(
                "BINDING_KIND_MISMATCH",
                "binding.kind must be sqlmesh for this validator.",
            )
        )
    binding_version = binding.get("binding_version")
    if not _is_integer(binding_version) or binding_version != BINDING_VERSION:
        issues.append(
            _issue(
                "UNSUPPORTED_BINDING_VERSION",
                "binding.binding_version must be integer 1.",
            )
        )

    semantic_packages = semantic.get("packages")
    binding_packages = binding.get("packages")
    if not isinstance(semantic_packages, list) or not semantic_packages:
        issues.append(_issue("INVALID_CONTRACT", "semantic.packages must be a non-empty list."))
        return issues, []
    if not isinstance(binding_packages, list) or not binding_packages:
        issues.append(_issue("INVALID_CONTRACT", "binding.packages must be a non-empty list."))
        return issues, []

    binding_by_package: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]], bool]] = {}
    for index, raw_package in enumerate(binding_packages):
        if not isinstance(raw_package, Mapping):
            issues.append(_issue("INVALID_BINDING_PACKAGE", f"binding.packages[{index}] must be a mapping."))
            continue
        binding_package = dict(raw_package)
        package_id = str(raw_package.get("package_id") or "").strip()
        package_valid = _validate_known_fields(
            binding_package,
            _BINDING_PACKAGE_FIELDS,
            label="SQLMesh binding package",
            code="INVALID_BINDING_PACKAGE",
            issues=issues,
            package_id=package_id,
        )
        if not _is_nonempty_string(raw_package.get("package_id")):
            issues.append(
                _issue(
                    "INVALID_BINDING_PACKAGE",
                    f"binding.packages[{index}] must include a non-empty package_id.",
                )
            )
            continue
        if package_id in binding_by_package:
            issues.append(
                _issue(
                    "DUPLICATE_BINDING_PACKAGE",
                    f"binding contains duplicate package_id {package_id}.",
                    package_id=package_id,
                )
            )
            continue
        accepted_hashes = binding_package.get("accepted_semantic_hashes")
        if "accepted_semantic_hashes" in binding_package:
            if not isinstance(accepted_hashes, list):
                issues.append(
                    _issue(
                        "INVALID_BINDING_PACKAGE",
                        "accepted_semantic_hashes must be a list.",
                        package_id=package_id,
                    )
                )
                package_valid = False
            else:
                seen_hashes: set[str] = set()
                for value in accepted_hashes:
                    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                        issues.append(
                            _issue(
                                "INVALID_BINDING_PACKAGE",
                                "accepted_semantic_hashes entries must be sha256: plus "
                                "64 lowercase hexadecimal characters.",
                                package_id=package_id,
                            )
                        )
                        package_valid = False
                    elif value in seen_hashes:
                        issues.append(
                            _issue(
                                "INVALID_BINDING_PACKAGE",
                                "accepted_semantic_hashes must not contain duplicates.",
                                package_id=package_id,
                            )
                        )
                        package_valid = False
                    seen_hashes.add(str(value))
        if "policy" in binding_package:
            policy, policy_valid = _validate_policy(
                binding_package.get("policy"),
                package_id=package_id,
                issues=issues,
            )
        else:
            policy, policy_valid = {}, True
        binding_rows, rows_valid = _binding_resource_rows(
            binding_package.get("resources"),
            package_id=package_id,
            issues=issues,
        )
        binding_package["policy"] = policy
        binding_by_package[package_id] = (
            binding_package,
            binding_rows,
            package_valid and policy_valid and rows_valid,
        )

    semantic_by_package: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]], bool]] = {}
    for index, raw_package in enumerate(semantic_packages):
        if not isinstance(raw_package, Mapping):
            issues.append(_issue("INVALID_SEMANTIC_PACKAGE", f"semantic.packages[{index}] must be a mapping."))
            continue
        semantic_package = dict(raw_package)
        package_id = str(raw_package.get("package_id") or "").strip()
        package_valid = _validate_known_fields(
            semantic_package,
            _SEMANTIC_PACKAGE_FIELDS,
            label="semantic package",
            code="INVALID_SEMANTIC_PACKAGE",
            issues=issues,
            package_id=package_id,
        )
        if not _is_nonempty_string(raw_package.get("package_id")):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_PACKAGE",
                    f"semantic.packages[{index}] must include a non-empty package_id.",
                )
            )
            continue
        if package_id in semantic_by_package:
            issues.append(
                _issue(
                    "DUPLICATE_SEMANTIC_PACKAGE",
                    f"semantic contains duplicate package_id {package_id}.",
                    package_id=package_id,
                )
            )
            continue
        namespace = semantic_package.get("namespace")
        if "namespace" in semantic_package and not isinstance(namespace, str):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_PACKAGE",
                    "semantic package namespace must be a string when provided.",
                    package_id=package_id,
                )
            )
            package_valid = False
        package_schema_version = semantic_package.get("package_schema_version")
        if package_schema_version is None:
            issues.append(
                _issue(
                    "PACKAGE_SCHEMA_VERSION_REQUIRED",
                    "semantic package package_schema_version is required.",
                    package_id=package_id,
                )
            )
            package_valid = False
        elif not _is_integer(package_schema_version) or package_schema_version != 1:
            issues.append(
                _issue(
                    "UNSUPPORTED_PACKAGE_SCHEMA_VERSION",
                    "semantic package package_schema_version must be integer 1.",
                    package_id=package_id,
                )
            )
            package_valid = False
        semantic_hash = semantic_package.get("semantic_hash")
        if not isinstance(semantic_hash, str) or not _SHA256_RE.fullmatch(semantic_hash):
            issues.append(
                _issue(
                    "INVALID_SEMANTIC_PACKAGE",
                    "semantic_hash must be sha256: followed by 64 lowercase hexadecimal characters.",
                    package_id=package_id,
                )
            )
            package_valid = False
        semantic_rows, rows_valid = _semantic_resource_rows(
            semantic_package.get("resources"),
            package_id=package_id,
            issues=issues,
        )
        semantic_by_package[package_id] = (
            semantic_package,
            semantic_rows,
            package_valid and rows_valid,
        )

    out: list[Mapping[str, Any]] = []
    for package_id in sorted(set(binding_by_package) - set(semantic_by_package)):
        issues.append(
            _issue(
                "SEMANTIC_PACKAGE_NOT_FOUND",
                f"SQLMesh binding package {package_id} has no matching semantic package.",
                package_id=package_id,
            )
        )
    for package_id in sorted(set(semantic_by_package) - set(binding_by_package)):
        issues.append(
            _issue(
                "SQLMESH_BINDING_PACKAGE_NOT_FOUND",
                f"No SQLMesh binding exists for semantic package {package_id}.",
                package_id=package_id,
            )
        )

    for package_id in sorted(set(semantic_by_package) & set(binding_by_package)):
        semantic_package, semantic_rows, semantic_valid = semantic_by_package[package_id]
        binding_package, binding_rows, binding_valid = binding_by_package[package_id]
        for semantic_model_id in sorted(set(binding_rows) - set(semantic_rows)):
            issues.append(
                _issue(
                    "SEMANTIC_RESOURCE_NOT_FOUND",
                    f"Binding resource {semantic_model_id} has no matching semantic resource.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )
        for semantic_model_id in sorted(set(semantic_rows) - set(binding_rows)):
            issues.append(
                _issue(
                    "SQLMESH_BINDING_RESOURCE_NOT_FOUND",
                    f"Semantic resource {semantic_model_id} has no matching SQLMesh binding resource.",
                    package_id=package_id,
                    semantic_model_id=semantic_model_id,
                )
            )

        merged_resources: list[dict[str, Any]] = []
        for semantic_model_id in sorted(set(semantic_rows) & set(binding_rows)):
            semantic_row = semantic_rows[semantic_model_id]
            binding_row = binding_rows[semantic_model_id]
            columns = semantic_row["columns"]
            merged = {**semantic_row, **binding_row, "columns": [dict(row) for row in columns]}
            merged_resources.append(merged)

        if semantic_valid and binding_valid:
            out.append(
                {
                    "package_id": package_id,
                    "namespace": semantic_package.get("namespace"),
                    "package_schema_version": semantic_package.get("package_schema_version"),
                    "semantic_hash": semantic_package.get("semantic_hash"),
                    "accepted_semantic_hashes": binding_package.get("accepted_semantic_hashes", []),
                    "policy": binding_package.get("policy", {}),
                    "resources": merged_resources,
                }
            )
    return issues, out


def packages(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if "contract_format_version" in spec:
        _, rows = _v1_packages(spec)
        return rows
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

    if "contract_format_version" in spec:
        version_issues, package_rows = _v1_packages(spec)
        issues.extend(version_issues)
    else:
        issues.append(
            ContractIssue(
                "LEGACY_CONTRACT_FORMAT",
                "warning",
                "",
                "",
                "Legacy packages: contracts remain readable for migration only; "
                "regenerate a contract_format_version: 1 payload.",
            )
        )
        package_rows = packages(spec)
    if not package_rows:
        if issues:
            return issues, []
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
            package_contract.get("package_id") or package_contract.get("id") or package_contract.get("name") or ""
        )
        policy_payload = package_contract.get("policy") if isinstance(package_contract.get("policy"), Mapping) else {}
        policy = ContractPolicy(
            severity=normalize_severity(policy_payload.get("severity", "error")),
            type_check=str(policy_payload.get("type_check", "ignore")),
            allow_extra_columns=bool_value(policy_payload.get("allow_extra_columns", True)),
            require_owner=bool_value(policy_payload.get("require_owner", False)),
            require_audits=bool_value(policy_payload.get("require_audits", False)),
        )
        legacy_contract_version = package_contract.get("contract_version")
        if "contract_format_version" not in spec and legacy_contract_version not in (None, 1):
            issues.append(
                ContractIssue(
                    "UNSUPPORTED_CONTRACT_VERSION",
                    "error",
                    package_id,
                    "",
                    "Legacy contract_version must be 1.",
                )
            )
            continue
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
) -> list[ContractIssue]:
    issues, resources = contract_resources(spec)
    for resource in resources:
        issues.extend(validate_resource(resource, snapshots))
    return issues


def validate_resource(
    resource: ContractResource,
    snapshots: Mapping[str, ResourceSnapshot],
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
                "SQLMESH_MODEL_NOT_FOUND",
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                f"Expected SQLMesh model {resource.target_name} was not found.",
            )
        ]
    if len(candidates) > 1:
        return [
            ContractIssue(
                "SQLMESH_MODEL_AMBIGUOUS",
                resource.severity,
                resource.package_id,
                resource.semantic_model_id,
                f"Expected SQLMesh model {resource.target_name} matched multiple models. Use a fully qualified name.",
            )
        ]
    snapshot = candidates[0]
    issues.extend(validate_metadata(resource, snapshot))
    issues.extend(validate_columns(resource, snapshot))
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


def validate_metadata(resource: ContractResource, snapshot: ResourceSnapshot) -> list[ContractIssue]:
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
                    f"Expected SQLMesh {field_name} {expected}, found {actual}.",
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
                f"Expected SQLMesh tag {tag} is missing.",
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
                f"Expected SQLMesh audit {audit} is missing.",
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


def validate_columns(resource: ContractResource, snapshot: ResourceSnapshot) -> list[ContractIssue]:
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
            detail = f"Missing SQLMesh column {name} required by Semantic Rails model {resource.semantic_model_id}"
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
                        f"SQLMesh column {actual_name} is not listed in the Semantic Rails contract "
                        "and allow_extra_columns is false.",
                    )
                )
    return issues


def first_present(payload: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None
