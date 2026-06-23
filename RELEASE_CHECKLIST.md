# Release Checklist

Before tagging a public release:

1. Update `pyproject.toml` `version`.
2. Update `CHANGELOG.md`.
3. Run `./scripts/run_integration_tests.sh`.
4. Install the package from a local wheel in a separate SQLMesh project.
5. Confirm `semantic-rails-sqlmesh-contracts check` passes for a real Semantic Rails payload.
6. Confirm a deliberate missing-column payload fails with `SQLMESH_COLUMN_MISSING`.
7. Confirm matrix mode across at least two SQLMesh projects or gateways.
8. Run any available live gateway smoke checks for release-supported engines.
9. Create a Git tag that matches the documented package revision.

The public package is release-ready only when the integration matrix, package
build, and at least one real SQLMesh project harness pass.
