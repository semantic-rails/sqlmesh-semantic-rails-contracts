# Release Checklist

Before tagging a public release:

1. Update `pyproject.toml` `version`; `__init__.__version__` is derived from installed metadata.
2. Update `CHANGELOG.md`.
3. Run the manual **Engine compatibility canary** workflow against the exact
   engine candidate tag or full commit SHA and record its run URL.
4. Replace the `compatibility.json` `engine_candidate_sha` placeholder with the
   exact 40-character commit selected by that canary. Never infer or invent it.
5. Verify public engine tag `v0.2.0` dereferences to that exact commit.
6. Run `python scripts/check_schema_compatibility.py`.
7. Validate the canonical, binding, composed-contract, and specialized
   `ValidationReportV1` schemas with all references resolved.
8. Test the minimum and newest supported SQLMesh dependency lines.
9. Confirm strict malformed-contract, duplicate, and one-to-one coverage tests.
10. Install the package from the candidate wheel in a separate SQLMesh project.
11. Confirm a missing-column payload fails with `SQLMESH_COLUMN_MISSING`.
12. Confirm matrix mode across at least two SQLMesh projects or gateways.
13. Run available live gateway smoke checks.
14. Verify the engine candidate has been published and that required CI passes
    against `semantic-rails>=0.2,<0.3` from public PyPI. Required CI never
    consumes engine `main`.
15. Verify the adapter tag exactly matches `pyproject.toml` and
    `compatibility.json`.
16. Build the wheel and sdist once, test that exact wheel, and generate
    `SHA256SUMS` plus `release-provenance.json`.
17. Publish those bytes through the protected `pypi` environment using OIDC
    Trusted Publishing.
18. Verify PyPI reports the exact wheel and sdist hashes before creating the
    GitHub Release.
19. Attach the exact artifacts, checksums, provenance, compatibility manifest,
    and public schemas to the matching immutable GitHub Release.

The public package is release-ready only when the integration matrix, package
build, schema checks, minimum/latest dependency matrix, and at least one real
SQLMesh project harness pass.
