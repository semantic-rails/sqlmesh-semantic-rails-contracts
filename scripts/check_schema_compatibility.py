#!/usr/bin/env python3
"""Fail when adapter-owned v1 schemas break the immutable release baseline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_MISSING = object()


def _display(value: Any) -> str:
    return "<missing>" if value is _MISSING else repr(value)


def _record(
    changes: list[dict[str, str]],
    *,
    artifact: str,
    path: str,
    kind: str,
    message: str,
) -> None:
    changes.append(
        {
            "artifact": artifact,
            "path": path,
            "kind": kind,
            "message": message,
        }
    )


def _record_keyword_change(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    field_name: str,
    artifact: str,
    path: str,
    breaking: list[dict[str, str]],
    additive: list[dict[str, str]],
) -> None:
    old = before.get(field_name, _MISSING)
    new = after.get(field_name, _MISSING)
    if old == new:
        return
    if old is _MISSING:
        target = breaking
        message = f"{field_name} was added and may narrow accepted payloads."
    elif new is _MISSING:
        target = additive
        message = f"{field_name} was removed and may widen accepted payloads."
    else:
        target = breaking
        message = f"{field_name} changed from {_display(old)} to {_display(new)}."
    _record(
        target,
        artifact=artifact,
        path=path,
        kind=f"{field_name}_changed",
        message=message,
    )


def _compare_schema(
    before: Any,
    after: Any,
    *,
    artifact: str,
    path: str,
    breaking: list[dict[str, str]],
    additive: list[dict[str, str]],
) -> None:
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        if before != after:
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind="schema_node_changed",
                message="A released schema node changed type or value.",
            )
        return

    before_required = {str(value) for value in before.get("required", []) or []}
    after_required = {str(value) for value in after.get("required", []) or []}
    for name in sorted(after_required - before_required):
        _record(
            breaking,
            artifact=artifact,
            path=path,
            kind="required_added",
            message=f"New required field {name!r}.",
        )
    for name in sorted(before_required - after_required):
        _record(
            additive,
            artifact=artifact,
            path=path,
            kind="required_removed",
            message=f"Field {name!r} is no longer required.",
        )

    for container_name in ("properties", "$defs", "patternProperties", "dependentSchemas"):
        before_rows = dict(before.get(container_name, {}) or {})
        after_rows = dict(after.get(container_name, {}) or {})
        for name in sorted(before_rows.keys() - after_rows.keys()):
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{container_name}_entry_removed",
                message=f"{container_name} entry {name!r} was removed.",
            )
        for name in sorted(after_rows.keys() - before_rows.keys()):
            potentially_narrowing = container_name in {
                "patternProperties",
                "dependentSchemas",
            } or (container_name == "properties" and before.get("additionalProperties", True) is not False)
            _record(
                breaking if potentially_narrowing else additive,
                artifact=artifact,
                path=path,
                kind=f"{container_name}_entry_added",
                message=(
                    f"{container_name} entry {name!r} was added and may narrow an open schema."
                    if potentially_narrowing
                    else f"{container_name} entry {name!r} was added."
                ),
            )
        for name in sorted(before_rows.keys() & after_rows.keys()):
            _compare_schema(
                before_rows[name],
                after_rows[name],
                artifact=artifact,
                path=f"{path}/{container_name}/{name}",
                breaking=breaking,
                additive=additive,
            )

    before_enum_value = before.get("enum", _MISSING)
    after_enum_value = after.get("enum", _MISSING)
    before_enum = set(before_enum_value) if isinstance(before_enum_value, list) else set()
    after_enum = set(after_enum_value) if isinstance(after_enum_value, list) else set()
    if before_enum_value is _MISSING and after_enum_value is not _MISSING:
        _record(
            breaking,
            artifact=artifact,
            path=path,
            kind="enum_added",
            message="enum was added and narrows accepted values.",
        )
    elif before_enum_value is not _MISSING and after_enum_value is _MISSING:
        _record(
            additive,
            artifact=artifact,
            path=path,
            kind="enum_removed",
            message="enum was removed and widens accepted values.",
        )
    elif before_enum_value is not _MISSING and after_enum_value is not _MISSING:
        for value in sorted(before_enum - after_enum, key=str):
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind="enum_value_removed",
                message=f"Enum value {value!r} was removed.",
            )
        for value in sorted(after_enum - before_enum, key=str):
            _record(
                additive,
                artifact=artifact,
                path=path,
                kind="enum_value_added",
                message=f"Enum value {value!r} was added.",
            )

    for field_name in ("$id", "$anchor", "$dynamicAnchor", "$ref", "$dynamicRef"):
        old = before.get(field_name, _MISSING)
        new = after.get(field_name, _MISSING)
        if old != new:
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_changed",
                message=f"{field_name} changed from {_display(old)} to {_display(new)}.",
            )

    for field_name in (
        "const",
        "type",
        "pattern",
        "format",
        "contentEncoding",
        "contentMediaType",
    ):
        _record_keyword_change(
            before=before,
            after=after,
            field_name=field_name,
            artifact=artifact,
            path=path,
            breaking=breaking,
            additive=additive,
        )

    for field_name in ("additionalProperties", "unevaluatedProperties"):
        old = before.get(field_name, True)
        new = after.get(field_name, True)
        if old is not False and new is False:
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_closed",
                message=f"{field_name} now rejects values it previously accepted.",
            )
        elif old is False and new is not False:
            _record(
                additive,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_opened",
                message=f"{field_name} now accepts values it previously rejected.",
            )
        elif isinstance(old, Mapping) and isinstance(new, Mapping):
            _compare_schema(
                old,
                new,
                artifact=artifact,
                path=f"{path}/{field_name}",
                breaking=breaking,
                additive=additive,
            )
        elif old != new:
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_changed",
                message=f"{field_name} changed shape.",
            )

    old_unique = bool(before.get("uniqueItems", False))
    new_unique = bool(after.get("uniqueItems", False))
    if not old_unique and new_unique:
        _record(
            breaking,
            artifact=artifact,
            path=path,
            kind="unique_items_enabled",
            message="uniqueItems now rejects duplicate array entries.",
        )
    elif old_unique and not new_unique:
        _record(
            additive,
            artifact=artifact,
            path=path,
            kind="unique_items_disabled",
            message="uniqueItems was removed and duplicate array entries are now accepted.",
        )

    for field_name in (
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "exclusiveMinimum",
        "minContains",
    ):
        old = before.get(field_name, _MISSING)
        new = after.get(field_name, _MISSING)
        if new is not _MISSING and (old is _MISSING or float(new) > float(old)):
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_increased",
                message=f"{field_name} became more restrictive.",
            )
        elif old is not _MISSING and (new is _MISSING or float(new) < float(old)):
            _record(
                additive,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_decreased",
                message=f"{field_name} became less restrictive.",
            )
    for field_name in (
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "exclusiveMaximum",
        "maxContains",
    ):
        old = before.get(field_name, _MISSING)
        new = after.get(field_name, _MISSING)
        if new is not _MISSING and (old is _MISSING or float(new) < float(old)):
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_decreased",
                message=f"{field_name} became more restrictive.",
            )
        elif old is not _MISSING and (new is _MISSING or float(new) > float(old)):
            _record(
                additive,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_increased",
                message=f"{field_name} became less restrictive.",
            )

    for field_name in ("items", "contains", "propertyNames"):
        old = before.get(field_name, _MISSING)
        new = after.get(field_name, _MISSING)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            _compare_schema(
                old,
                new,
                artifact=artifact,
                path=f"{path}/{field_name}",
                breaking=breaking,
                additive=additive,
            )
        elif old != new:
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{field_name}_changed",
                message=f"{field_name} changed shape or presence.",
            )

    before_dependencies = dict(before.get("dependentRequired", {}) or {})
    after_dependencies = dict(after.get("dependentRequired", {}) or {})
    for name in sorted(set(before_dependencies) | set(after_dependencies)):
        old = set(before_dependencies.get(name, []))
        new = set(after_dependencies.get(name, []))
        for dependency in sorted(new - old):
            _record(
                breaking,
                artifact=artifact,
                path=f"{path}/dependentRequired/{name}",
                kind="dependent_required_added",
                message=f"New dependent required field {dependency!r}.",
            )
        for dependency in sorted(old - new):
            _record(
                additive,
                artifact=artifact,
                path=f"{path}/dependentRequired/{name}",
                kind="dependent_required_removed",
                message=f"Dependent required field {dependency!r} was removed.",
            )

    for combinator in ("allOf", "anyOf", "oneOf", "prefixItems"):
        before_rows = before.get(combinator)
        after_rows = after.get(combinator)
        if before_rows is None:
            if after_rows is not None:
                _record(
                    breaking,
                    artifact=artifact,
                    path=path,
                    kind=f"{combinator}_added",
                    message=f"{combinator} was added and may narrow accepted payloads.",
                )
            continue
        if not isinstance(before_rows, list) or not isinstance(after_rows, list):
            if before_rows != after_rows:
                _record(
                    breaking,
                    artifact=artifact,
                    path=path,
                    kind=f"{combinator}_changed",
                    message=f"{combinator} changed shape.",
                )
            continue
        if len(before_rows) != len(after_rows):
            _record(
                breaking,
                artifact=artifact,
                path=path,
                kind=f"{combinator}_length_changed",
                message=f"{combinator} branch count changed.",
            )
        for index, (before_row, after_row) in enumerate(zip(before_rows, after_rows, strict=False)):
            _compare_schema(
                before_row,
                after_row,
                artifact=artifact,
                path=f"{path}/{combinator}/{index}",
                breaking=breaking,
                additive=additive,
            )

    for conditional in ("not", "if", "then", "else"):
        old = before.get(conditional, _MISSING)
        new = after.get(conditional, _MISSING)
        if old == new:
            continue
        _record(
            breaking,
            artifact=artifact,
            path=path,
            kind=f"{conditional}_changed",
            message=f"{conditional} changed and requires a new schema major or manual proof.",
        )


def compare_directories(baseline: Path, current: Path, names: list[str]) -> dict[str, Any]:
    breaking: list[dict[str, str]] = []
    additive: list[dict[str, str]] = []
    for name in names:
        baseline_path = baseline / name
        current_path = current / name
        if not baseline_path.is_file():
            _record(
                breaking,
                artifact=name,
                path="/",
                kind="baseline_missing",
                message="The immutable released baseline is missing.",
            )
            continue
        if not current_path.is_file():
            _record(
                breaking,
                artifact=name,
                path="/",
                kind="artifact_removed",
                message="A released schema artifact was removed.",
            )
            continue
        _compare_schema(
            json.loads(baseline_path.read_text(encoding="utf-8")),
            json.loads(current_path.read_text(encoding="utf-8")),
            artifact=name,
            path="/",
            breaking=breaking,
            additive=additive,
        )
    return {
        "ok": not breaking,
        "baseline": str(baseline),
        "current": str(current),
        "breaking_changes": breaking,
        "additive_changes": additive,
        "summary": {
            "breaking": len(breaking),
            "additive": len(additive),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "compatibility" / "baseline" / "v1",
    )
    parser.add_argument("--current", type=Path, default=ROOT / "schemas")
    args = parser.parse_args(argv)

    manifest = json.loads((ROOT / "compatibility.json").read_text(encoding="utf-8"))
    names = [str(name) for name in manifest["adapter_owned_schema_files"]]
    report = compare_directories(args.baseline, args.current, names)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
