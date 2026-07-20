#!/usr/bin/env python3
"""Verify package, compatibility, schema, tag, and engine-candidate identities."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ENGINE_RELEASE_STATES = {"candidate", "released"}


def _dependency_matches(rows: list[str], name: str, specifier: str) -> bool:
    normalized_name = name.lower().replace("_", "-")
    expected = specifier.replace(" ", "")
    for row in rows:
        normalized = row.lower().replace("_", "-").replace(" ", "")
        if normalized.startswith(normalized_name) and expected in normalized:
            return True
    return False


def _resolve_remote_tag(repository: str, tag: str) -> str:
    result = subprocess.run(
        [
            "git",
            "ls-remote",
            repository,
            f"refs/tags/{tag}",
            f"refs/tags/{tag}^{{}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    direct: str | None = None
    peeled: str | None = None
    for line in result.stdout.splitlines():
        sha, ref = line.split(maxsplit=1)
        if ref.endswith("^{}"):
            peeled = sha
        elif ref == f"refs/tags/{tag}":
            direct = sha
    resolved = peeled or direct
    if resolved is None:
        raise SystemExit(f"Engine tag {tag} was not found in {repository}.")
    return resolved


def _resolve_local_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _append_github_values(path: Path, rows: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in rows.items():
            if "\n" in value or "\r" in value:
                raise SystemExit(f"GitHub output {key} must be a single line.")
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--verify-adapter-tag", action="store_true")
    parser.add_argument("--verify-engine-tag", action="store_true")
    parser.add_argument("--github-env", type=Path, default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args(argv)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    manifest = json.loads((ROOT / "compatibility.json").read_text(encoding="utf-8"))
    distribution = manifest["distribution"]
    engine = manifest["engine"]
    sqlmesh = manifest["sqlmesh"]
    release_state = engine.get("release_state")

    version = str(project["version"])
    if distribution["name"] != project["name"] or distribution["version"] != version:
        raise SystemExit("compatibility.json distribution identity must match pyproject.toml.")
    if distribution["python"] != project["requires-python"]:
        raise SystemExit("compatibility.json Python requirement must match pyproject.toml.")
    if args.tag is not None and args.tag != f"v{version}":
        raise SystemExit(f"Release tag {args.tag} does not match package version v{version}.")
    if engine.get("name") != "semantic-rails":
        raise SystemExit("compatibility.json engine.name must be semantic-rails.")
    if release_state not in ENGINE_RELEASE_STATES:
        raise SystemExit("compatibility.json engine.release_state must be candidate or released.")
    adapter_source_sha: str | None = None
    if args.verify_adapter_tag:
        if args.tag is None:
            raise SystemExit("--verify-adapter-tag requires --tag.")
        adapter_source_sha = _resolve_local_commit("HEAD")
        tagged_source_sha = _resolve_local_commit(f"refs/tags/{args.tag}")
        if tagged_source_sha != adapter_source_sha:
            raise SystemExit(
                f"Adapter tag {args.tag} resolves to {tagged_source_sha}, not checked-out source {adapter_source_sha}."
            )

    dependencies = [str(value) for value in project.get("dependencies", [])]
    export_dependencies = [str(value) for value in project.get("optional-dependencies", {}).get("export", [])]
    if not _dependency_matches(dependencies, "sqlmesh", str(sqlmesh["specifier"])):
        raise SystemExit("The SQLMesh compatibility specifier does not match pyproject.toml.")
    if not _dependency_matches(export_dependencies, "semantic-rails", str(engine["specifier"])):
        raise SystemExit("The engine compatibility specifier does not match the export extra.")

    expected_prefix = "https://semantic-rails.com/schemas/"
    contract_schema_files: set[str] = set()
    adapter_owned_schema_files: set[str] = set()
    for contract_name, contract in manifest["contracts"].items():
        schema_id = str(contract["schema_id"])
        if not schema_id.startswith(expected_prefix):
            raise SystemExit(f"{contract_name} schema_id must use {expected_prefix}.")
        schema_filename = Path(urlparse(schema_id).path).name
        contract_schema_files.add(schema_filename)
        if contract["owner"] == distribution["name"]:
            adapter_owned_schema_files.add(schema_filename)
        schema_path = ROOT / "schemas" / schema_filename
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if schema.get("$id") != schema_id:
            raise SystemExit(f"{schema_path.name} $id does not match compatibility.json.")
    actual_schema_files = {path.name for path in (ROOT / "schemas").glob("*.json")}
    if len(contract_schema_files) != len(manifest["contracts"]) or contract_schema_files != actual_schema_files:
        raise SystemExit("compatibility.json contracts must enumerate every public schema exactly once.")
    declared_adapter_schemas = {str(name) for name in manifest["adapter_owned_schema_files"]}
    if declared_adapter_schemas != adapter_owned_schema_files:
        raise SystemExit("adapter_owned_schema_files must match contract ownership.")
    baseline_schema_files = {path.name for path in (ROOT / "compatibility" / "baseline" / "v1").glob("*.json")}
    if baseline_schema_files != adapter_owned_schema_files:
        raise SystemExit("The immutable v1 baseline must contain every adapter-owned schema exactly once.")

    candidate_sha = engine.get("engine_candidate_sha")
    candidate_ready = isinstance(candidate_sha, str) and SHA_RE.fullmatch(candidate_sha) is not None
    if not candidate_ready:
        raise SystemExit(f"Engine release_state {release_state} requires an exact engine_candidate_sha.")
    resolved_engine_sha: str | None = None
    if args.verify_engine_tag:
        if release_state != "released":
            raise SystemExit(
                "Set compatibility.json engine.release_state to released only "
                "after the approved engine artifact is on PyPI."
            )
        if not candidate_ready:
            raise SystemExit("Cannot verify the engine tag until engine_candidate_sha is filled.")
        resolved_engine_sha = _resolve_remote_tag(str(engine["repository"]), str(engine["tag"]))
        if resolved_engine_sha != candidate_sha:
            raise SystemExit(
                f"Engine tag {engine['tag']} resolves to {resolved_engine_sha}, not approved candidate {candidate_sha}."
            )

    engine_values = {
        "ENGINE_RELEASE_STATE": str(release_state),
        "ENGINE_VERSION": str(engine["version"]),
        "ENGINE_CANDIDATE_SHA": str(candidate_sha or ""),
        "ENGINE_MINIMUM_SPEC": f"{engine['name']}=={engine['version']}",
        "ENGINE_COMPATIBLE_SPEC": f"{engine['name']}{engine['specifier']}",
    }
    if args.github_env is not None:
        rows = {
            "ADAPTER_VERSION": version,
            "ADAPTER_SOURCE_SHA": str(adapter_source_sha or ""),
            "ENGINE_TAG": str(engine["tag"]),
            "SQLMESH_RELEASE_TEST_VERSION": str(sqlmesh["release_test_version"]),
            **engine_values,
        }
        _append_github_values(args.github_env, rows)
    if args.github_output is not None:
        _append_github_values(
            args.github_output,
            {key.lower(): value for key, value in engine_values.items()},
        )

    print(
        json.dumps(
            {
                "ok": True,
                "distribution": {
                    "name": project["name"],
                    "version": version,
                    "tag": args.tag,
                    "source_commit": adapter_source_sha,
                },
                "engine": {
                    "version": engine["version"],
                    "tag": engine["tag"],
                    "release_state": release_state,
                    "engine_candidate_sha": candidate_sha,
                    "candidate_ready": candidate_ready,
                    "resolved_tag_sha": resolved_engine_sha,
                },
                "sqlmesh": {
                    "specifier": sqlmesh["specifier"],
                    "release_test_version": sqlmesh["release_test_version"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
