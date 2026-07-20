#!/usr/bin/env python3
"""Verify that PyPI recorded the exact wheel and sdist bytes built in CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_artifacts(dist_dir: Path) -> dict[str, str]:
    paths = sorted([*dist_dir.glob("*.whl"), *dist_dir.glob("*.tar.gz")])
    if len(paths) != 2:
        raise SystemExit("Expected exactly one wheel and one sdist to verify.")
    return {path.name: sha256(path) for path in paths}


def fetch_release(package: str, version: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://pypi.org/pypi/{package}/{version}/json",
        headers={"User-Agent": "sqlmesh-semantic-rails-contracts-release-verifier/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return dict(json.load(response))


def compare_release(expected: dict[str, str], payload: dict[str, Any]) -> tuple[bool, str]:
    published = {str(row["filename"]): str(row.get("digests", {}).get("sha256", "")) for row in payload.get("urls", [])}
    if set(published) != set(expected):
        return False, f"Published filenames {sorted(published)} do not match {sorted(expected)}."
    mismatches = [name for name, digest in expected.items() if published.get(name) != digest]
    if mismatches:
        return False, f"Published SHA-256 mismatch for {', '.join(sorted(mismatches))}."
    return True, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--interval-seconds", type=float, default=10)
    args = parser.parse_args(argv)

    expected = expected_artifacts(args.dist_dir)
    last_error = ""
    for attempt in range(1, args.attempts + 1):
        try:
            payload = fetch_release(args.package, args.version)
            ok, last_error = compare_release(expected, payload)
            if ok:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "package": args.package,
                            "version": args.version,
                            "artifacts": expected,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        if attempt < args.attempts:
            time.sleep(args.interval_seconds)
    raise SystemExit(f"PyPI exact-byte verification failed: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
