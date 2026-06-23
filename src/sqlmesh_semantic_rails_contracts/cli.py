"""Command line interface for SQLMesh Semantic Rails contract checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .checker import assert_report, check_project, format_issue
from .exporter import build_sqlmesh_contract
from .matrix import run_matrix, write_report


def parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="semantic-rails-sqlmesh-contracts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check one SQLMesh project")
    check.add_argument("--project-dir", default=".")
    check.add_argument("--contract-file", default="semantic_rails_contract.yml")
    check.add_argument("--gateway", default=None)
    check.add_argument("--json", action="store_true", help="Print JSON report")
    check.add_argument("--warn-only", action="store_true", help="Print errors without exiting non-zero")

    report = subparsers.add_parser("report", help="Print a JSON report for one SQLMesh project")
    report.add_argument("--project-dir", default=".")
    report.add_argument("--contract-file", default="semantic_rails_contract.yml")
    report.add_argument("--gateway", default=None)

    matrix = subparsers.add_parser("matrix", help="Check multiple SQLMesh projects or gateways")
    matrix.add_argument("config")
    matrix.add_argument("--output", "-o", default=None)

    export = subparsers.add_parser("export", help="Export a SQLMesh contract payload from Semantic Rails YAML")
    export.add_argument("semantic_package")
    export.add_argument("--output", "-o")
    export.add_argument("--sqlmesh-model-prefix", default="")
    export.add_argument("--sqlmesh-model-suffix", default="")
    export.add_argument("--model-map", action="append", default=[])
    export.add_argument("--include-model", action="append", default=[])
    export.add_argument("--sqlmesh-project", default=None)
    export.add_argument("--sqlmesh-gateway", default=None)
    export.add_argument("--sqlmesh-kind", default=None)
    export.add_argument("--owner", default=None)
    export.add_argument("--tag", action="append", default=[])
    export.add_argument("--audit", action="append", default=[])
    export.add_argument("--sqlmesh-catalog", default=None)
    export.add_argument("--sqlmesh-schema", default=None)
    export.add_argument("--sqlmesh-identifier", default=None)
    export.add_argument("--sqlmesh-relation-name", default=None)
    export.add_argument("--severity", default="error", choices=["error", "warn"])
    export.add_argument("--type-check", default="ignore", choices=["ignore", "compatible", "exact"])
    export.add_argument("--allow-extra-columns", default=True, type=parse_bool)
    export.add_argument("--require-owner", default=False, type=parse_bool)
    export.add_argument("--require-audits", default=False, type=parse_bool)

    args = parser.parse_args(argv)

    if args.command == "check":
        result = check_project(
            project_dir=Path(args.project_dir),
            contract_file=Path(args.contract_file),
            gateway=args.gateway,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
            has_errors = any(issue.get("severity", "error") != "warn" for issue in result["issues"])
            return 0 if args.warn_only or not has_errors else 1
        assert_report(result, warn_only=args.warn_only)
        return 0
    if args.command == "report":
        result = check_project(
            project_dir=Path(args.project_dir),
            contract_file=Path(args.contract_file),
            gateway=args.gateway,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "matrix":
        result = run_matrix(Path(args.config))
        output_path = Path(args.output) if args.output else None
        write_report(result, output_path)
        stream = sys.stdout if output_path else sys.stderr
        status = "passed" if result["ok"] else "failed"
        warning_suffix = f" with {result['warning_count']} warning(s)" if result.get("warning_count") else ""
        print(
            f"Semantic Rails SQLMesh contract matrix {status}: "
            f"{result['passed_count']}/{result['project_count']} project(s) passed{warning_suffix}.",
            file=stream,
        )
        for project in result["projects"]:
            if project.get("error"):
                print(f"ERROR [{project.get('name')}] {project['error']}", file=stream)
                continue
            for issue in project.get("report", {}).get("issues", []):
                if issue.get("severity", "error") == "warn" or not project.get("ok"):
                    print(format_issue(issue), file=stream)
        return 0 if result["ok"] else 1
    if args.command == "export":
        payload = build_sqlmesh_contract(args)
        text = yaml.safe_dump(payload, sort_keys=False)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
