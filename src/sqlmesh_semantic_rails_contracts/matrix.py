"""Run contract checks across multiple SQLMesh projects or gateways."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .checker import check_project


def run_matrix(config_path: Path) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("matrix config must be a YAML mapping")
    defaults = dict(config.get("defaults") or {})
    projects = config.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("matrix config must define a non-empty projects list")

    results = []
    for raw_project in projects:
        if not isinstance(raw_project, dict):
            raise ValueError("each projects entry must be a mapping")
        project = {**defaults, **raw_project}
        name = str(project.get("name") or project.get("project_dir") or project.get("gateway") or "<unnamed>")
        project_dir = resolve(config_path.parent, project.get("project_dir", "."))
        contract_file = resolve(project_dir, project["contract_file"]) if project.get("contract_file") else None
        contract = project.get("contract")
        try:
            report = check_project(
                project_dir=project_dir,
                contract=contract,
                contract_file=contract_file,
                gateway=project.get("gateway"),
            )
            errors = [issue for issue in report["issues"] if issue.get("severity", "error") not in {"warn", "warning"}]
            warnings = [issue for issue in report["issues"] if issue.get("severity", "error") in {"warn", "warning"}]
            results.append(
                {
                    "name": name,
                    "ok": not errors,
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "project_dir": str(project_dir),
                    "gateway": project.get("gateway"),
                    "report": report,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "name": name,
                    "ok": False,
                    "error_count": 1,
                    "warning_count": 0,
                    "project_dir": str(project_dir),
                    "gateway": project.get("gateway"),
                    "error": str(exc),
                }
            )
    failed = [result for result in results if not result["ok"]]
    warning_count = sum(int(result.get("warning_count", 0)) for result in results)
    return {
        "report_format_version": 1,
        "report_kind": "sqlmesh_contract_matrix",
        "ok": not failed,
        "project_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "warning_count": warning_count,
        "projects": results,
    }


def resolve(base: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def write_report(report: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
