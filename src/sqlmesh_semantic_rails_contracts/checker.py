"""SQLMesh Semantic Rails contract checker."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from semantic_rails_contracts_core import (
    collect_contract_issues,
    contract_metadata,
    contract_summary,
    load_contract_file,
)
from semantic_rails_contracts_core.contracts import REPORT_FORMAT_VERSION

from . import __version__
from .sqlmesh_adapter import load_sqlmesh_snapshots


def check_project(
    *,
    project_dir: Path,
    contract: Mapping[str, Any] | None = None,
    contract_file: Path | None = None,
    gateway: str | None = None,
) -> dict[str, Any]:
    if contract_file and contract is not None:
        raise ValueError("Use contract or contract_file, not both.")
    project_dir = project_dir.expanduser().resolve()
    if contract_file and not contract_file.is_absolute():
        contract_file = project_dir / contract_file
    spec = dict(
        contract
        if contract is not None
        else load_contract_file(contract_file or project_dir / "semantic_rails_contract.yml")
    )
    snapshots = load_sqlmesh_snapshots(project_dir, gateway=gateway)
    issues = collect_contract_issues(
        spec,
        snapshots,
        framework="SQLMesh",
        not_found_code="SQLMESH_MODEL_NOT_FOUND",
        ambiguous_code="SQLMESH_MODEL_AMBIGUOUS",
    )
    model_count = len({snapshot.name for snapshot in snapshots.values()})
    errors, warnings = split_issues([issue.to_dict() for issue in issues])
    return {
        "report_format_version": REPORT_FORMAT_VERSION,
        "validator": {
            "name": "sqlmesh-semantic-rails-contracts",
            "version": __version__,
        },
        "input": contract_metadata(spec),
        "ok": not errors,
        "summary": {
            **contract_summary(spec),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "sqlmesh_model_count": model_count,
        },
        "issues": [issue.to_dict() for issue in issues],
    }


def split_issues(issues: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    warnings: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for issue in issues:
        if issue.get("severity", "error") in {"warn", "warning"}:
            warnings.append(issue)
        else:
            errors.append(issue)
    return errors, warnings


def format_issue(issue: Mapping[str, str]) -> str:
    scope = issue.get("package_id", "")
    if issue.get("semantic_model_id"):
        model_id = issue["semantic_model_id"]
        scope = f"{scope}.{model_id}" if scope else model_id
    return f"{issue.get('severity', 'error').upper()} {issue.get('code')} [{scope}] {issue.get('message')}"


def assert_report(report: Mapping[str, Any], warn_only: bool = False) -> None:
    errors, warnings = split_issues(list(report.get("issues", [])))
    for warning in warnings:
        print(format_issue(warning))
    if errors:
        message = "Semantic Rails SQLMesh contract check failed with " + str(len(errors)) + " error(s):\n"
        message += "\n".join(format_issue(issue) for issue in errors)
        if warn_only:
            print(message)
        else:
            raise SystemExit(message)
    summary = report.get("summary", {})
    resource_count = summary.get("resource_count", 0)
    package_count = summary.get("package_count", 0)
    if errors and warn_only:
        print(
            "Semantic Rails SQLMesh contract check completed with "
            f"{len(errors)} warn-only error(s) for {resource_count} resource contract(s) "
            f"across {package_count} package(s)."
        )
    elif warnings:
        print(
            "Semantic Rails SQLMesh contract check passed with "
            f"{len(warnings)} warning(s) for {resource_count} resource contract(s) "
            f"across {package_count} package(s)."
        )
    else:
        print(
            "Semantic Rails SQLMesh contract check passed for "
            f"{resource_count} resource contract(s) across {package_count} package(s)."
        )
