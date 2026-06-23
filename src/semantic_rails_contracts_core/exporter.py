"""Export Semantic Rails YAML packages to framework contract payloads."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

try:
    from sqlglot import exp, parse_one
except ModuleNotFoundError:  # pragma: no cover - exercised when sqlglot is not installed.
    exp = None  # type: ignore[assignment]
    parse_one = None  # type: ignore[assignment]

SQL_KEYWORDS = {
    "and",
    "as",
    "case",
    "cast",
    "coalesce",
    "date",
    "distinct",
    "else",
    "end",
    "false",
    "from",
    "interval",
    "is",
    "not",
    "null",
    "or",
    "then",
    "true",
    "when",
}

EXPRESSION_CHILD_KEYS = {"else", "expression", "expr", "input", "left", "right", "then", "when", "whens"}
GENERATED_CONTRACT_NAMES = {
    "semantic_rails_contract.yml",
    "semantic_rails_contract.yaml",
    "semantic_rails_contracts.yml",
    "semantic_rails_contracts.yaml",
}
IGNORED_PACKAGE_DIRS = {".git", ".sqlmesh", ".venv", "__pycache__", "dbt_packages", "logs", "target"}


def load_yaml(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def load_package_documents(root: Path) -> list[dict[str, Any]]:
    if root.is_file():
        return [load_yaml(root)]
    docs: list[dict[str, Any]] = []
    for path in iter_package_yaml_files(root):
        docs.append(load_yaml(path))
    return docs


def package_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if root.is_file():
        digest.update(root.read_bytes())
        return "sha256:" + digest.hexdigest()
    for path in iter_package_yaml_files(root):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def iter_package_yaml_files(root: Path) -> list[Path]:
    paths = [*root.rglob("*.yml"), *root.rglob("*.yaml")]
    out: list[Path] = []
    for path in sorted(set(paths)):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part in IGNORED_PACKAGE_DIRS for part in relative_parts):
            continue
        if path.name in GENERATED_CONTRACT_NAMES or path.name.startswith("semantic_rails_contract_"):
            continue
        out.append(path)
    return out


def collect_package_meta(docs: list[dict[str, Any]]) -> dict[str, Any]:
    for doc in docs:
        if isinstance(doc.get("package"), dict):
            package = dict(doc["package"])
            return {
                "package_id": package.get("id") or package.get("name") or "",
                "namespace": package.get("namespace") or package.get("id") or "",
                "schema_version": doc.get("schema_version", 1),
            }
    return {"package_id": "", "namespace": "", "schema_version": 1}


def collect_entities(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for doc in docs:
        graph = doc.get("graph") or {}
        for name, payload in dict(graph.get("entities") or {}).items():
            entities[str(name)] = dict(payload or {})
    return entities


def iter_model_payloads(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for doc in docs:
        if isinstance(doc.get("model"), dict):
            models.append(dict(doc["model"]))
        for name, payload in dict(doc.get("models") or {}).items():
            row = dict(payload or {})
            row.setdefault("id", str(name))
            models.append(row)
    return models


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def add_column(columns: dict[str, set[str]], name: str | None, required_by: str) -> None:
    if not name:
        return
    clean = str(name).strip()
    if not clean or clean == "*":
        return
    if "." in clean:
        clean = clean.split(".")[-1]
    columns.setdefault(clean, set()).add(required_by)


def columns_from_expr(expr: Any) -> set[str]:
    found: set[str] = set()
    if expr is None:
        return found
    if isinstance(expr, str):
        return columns_from_sql_string(expr)
    if isinstance(expr, list):
        for item in expr:
            found.update(columns_from_expr(item))
        return found
    if isinstance(expr, dict):
        if expr.get("kind") == "column" and expr.get("column"):
            found.add(str(expr["column"]))
        for key, value in expr.items():
            if key in EXPRESSION_CHILD_KEYS:
                found.update(columns_from_expr(value))
        return found
    return found


def columns_from_sql_string(expr: str) -> set[str]:
    parsed_columns = columns_from_sqlglot(expr)
    if parsed_columns:
        return parsed_columns
    return columns_from_tokens(expr)


def columns_from_sqlglot(expr: str) -> set[str]:
    if parse_one is None or exp is None:
        return set()
    try:
        parsed = parse_one(expr, error_level="ignore")
    except Exception:
        return set()
    if parsed is None:
        return set()
    return {column.name for column in parsed.find_all(exp.Column) if column.name and column.name != "*"}


def columns_from_tokens(expr: str) -> set[str]:
    found: set[str] = set()
    without_literals = re.sub(r"'([^']|'')*'", " ", expr)
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_\.]*", without_literals):
        token = match.group(0)
        bare = token.split(".")[-1].lower()
        remainder = without_literals[match.end() :].lstrip()
        if bare in SQL_KEYWORDS or bare.isdigit() or remainder.startswith("("):
            continue
        found.add(token.split(".")[-1])
    return found


def model_required_columns(model: dict[str, Any], entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    columns: dict[str, set[str]] = {}
    model_id = str(model.get("id") or model.get("name") or "")

    for entity_name, payload in dict(model.get("entities") or {}).items():
        entity_payload = dict(payload or {})
        for name in columns_from_expr(entity_payload.get("expr")):
            add_column(columns, name, f"entity.{entity_name}")
        if not entity_payload.get("expr"):
            entity = entities.get(str(entity_name), {})
            for key in as_list(entity.get("key")):
                add_column(columns, key, f"entity.{entity_name}")

    for time_name, payload in dict(model.get("times") or {}).items():
        row = dict(payload or {})
        add_column(columns, row.get("column") or time_name, f"time.{time_name}")

    for dimension_name, payload in dict(model.get("dimensions") or {}).items():
        row = dict(payload or {})
        add_column(columns, row.get("column") or dimension_name, f"dimension.{dimension_name}")
        for name in columns_from_expr(row.get("expr")):
            add_column(columns, name, f"dimension.{dimension_name}")

    for measure_name, payload in dict(model.get("measures") or {}).items():
        row = dict(payload or {})
        add_column(columns, row.get("entity_key"), f"measure.{measure_name}")
        for name in columns_from_expr(row.get("expr")):
            add_column(columns, name, f"measure.{measure_name}")

    return [
        {"name": name, "required_by": sorted(required_by)}
        for name, required_by in sorted(columns.items())
        if name and name != model_id
    ]


def parse_model_map(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values:
        left, sep, right = value.partition("=")
        if not sep or not left.strip() or not right.strip():
            raise ValueError(f"Invalid mapping {value!r}; expected semantic_model=target_model")
        out[left.strip()] = right.strip()
    return out
