# Changelog

## 0.2.0

- Consolidates SQLMesh-only validation and export into the adapter package;
  removes the unreleased `semantic_rails_contracts_core` implementation namespace.
  The CLI, schema accessor, wire contracts, and engine-free runtime are unchanged.
- Omits unselected packages during filtered export so multi-package
  `--include-model` output remains a valid semantic/binding contract.

- Makes the engine the sole semantic contract and fingerprint producer.
- Separates `contract_format_version` from SQLMesh `binding_version`.
- Adds schema-parity validation for versions, producers, package/resource
  identity, hashes, unknown fields, duplicates, and one-to-one coverage.
- Adds public canonical, binding, composed-contract, and specialized
  validation-report schemas with an offline schema accessor.
- Adds `ValidationReportV1` for agent and CI consumers.
- Keeps legacy payloads readable during the 0.2 transition while emitting only v1.
- Adds a machine-readable compatibility manifest and immutable schema baseline.
- Adds minimum/latest SQLMesh compatibility plus build-once, exact-byte,
  provenance-producing Trusted Publishing automation.

## 0.1.0

Initial public release candidate.

- Adds `semantic-rails-sqlmesh-contracts check` for SQLMesh contract checks.
- Adds `report`, `matrix`, and `export` command paths.
- Adds framework-neutral Semantic Rails contract parsing and export utilities.
- Adds SQLMesh metadata checks for model existence, kind, owner, tags, audits,
  relation metadata, columns, types, extra-column strictness, and Semantic Rails
  hash pinning.
- Adds integration fixtures and release-readiness checks.
