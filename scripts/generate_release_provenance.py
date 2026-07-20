#!/usr/bin/env python3
"""Generate checksums and machine-readable provenance for verified release bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
from importlib.metadata import version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--engine-wheel-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args(argv)

    manifest_path = ROOT / "compatibility.json"
    compatibility = json.loads(manifest_path.read_text(encoding="utf-8"))
    adapter_version = str(compatibility["distribution"]["version"])
    engine_version = str(compatibility["engine"]["version"])
    sqlmesh_version = str(compatibility["sqlmesh"]["release_test_version"])
    if version("sqlmesh-semantic-rails-contracts") != adapter_version:
        raise SystemExit("Installed adapter does not match compatibility.json.")
    if version("semantic-rails") != engine_version:
        raise SystemExit("Installed engine does not match compatibility.json.")
    if version("sqlmesh") != sqlmesh_version:
        raise SystemExit("Installed SQLMesh does not match compatibility.json release_test_version.")
    if args.tag != f"v{adapter_version}":
        raise SystemExit("Release tag does not match the installed adapter version.")
    if SHA_RE.fullmatch(args.git_sha) is None:
        raise SystemExit("--git-sha must be the exact 40-character adapter commit.")
    engine_candidate_sha = compatibility["engine"].get("engine_candidate_sha")
    if not isinstance(engine_candidate_sha, str) or SHA_RE.fullmatch(engine_candidate_sha) is None:
        raise SystemExit("compatibility.json must contain the exact engine candidate commit.")

    adapter_wheels = sorted(args.dist_dir.glob("*.whl"))
    adapter_sdists = sorted(args.dist_dir.glob("*.tar.gz"))
    distributions = [*adapter_wheels, *adapter_sdists]
    engine_wheels = sorted(args.engine_wheel_dir.glob("semantic_rails-*.whl"))
    if len(adapter_wheels) != 1 or len(adapter_sdists) != 1 or len(engine_wheels) != 1:
        raise SystemExit("Expected one adapter wheel, one adapter sdist, and one exact engine wheel.")
    adapter_stem = f"sqlmesh_semantic_rails_contracts-{adapter_version}"
    if not adapter_wheels[0].name.startswith(f"{adapter_stem}-"):
        raise SystemExit("Adapter wheel filename does not match compatibility.json.")
    if adapter_sdists[0].name != f"{adapter_stem}.tar.gz":
        raise SystemExit("Adapter sdist filename does not match compatibility.json.")
    if not engine_wheels[0].name.startswith(f"semantic_rails-{engine_version}-"):
        raise SystemExit("Engine wheel filename does not match compatibility.json.")

    schemas = []
    for path in sorted((ROOT / "schemas").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        schemas.append(
            {
                **artifact(path),
                "schema_id": payload.get("$id"),
            }
        )

    provenance = {
        "provenance_format_version": 1,
        "release": {
            "distribution": compatibility["distribution"]["name"],
            "version": adapter_version,
            "tag": args.tag,
            "source_commit": args.git_sha,
        },
        "engine_candidate": {
            "distribution": compatibility["engine"]["name"],
            "version": engine_version,
            "tag": compatibility["engine"]["tag"],
            "source_commit": engine_candidate_sha,
            "wheel": artifact(engine_wheels[0]),
        },
        "resolved_test_environment": {
            "python": platform.python_version(),
            "sqlmesh": version("sqlmesh"),
            "semantic-rails": version("semantic-rails"),
            "sqlmesh-semantic-rails-contracts": version("sqlmesh-semantic-rails-contracts"),
        },
        "artifacts": [artifact(path) for path in distributions],
        "schemas": schemas,
        "compatibility_manifest": {
            **artifact(manifest_path),
            "manifest_version": compatibility["manifest_version"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksums = "".join(f"{row['sha256']}  {row['filename']}\n" for row in provenance["artifacts"])
    (args.output.parent / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
