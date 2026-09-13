# Contributing

Run the full local matrix against an engine checkout before opening a change:

```shell
SEMANTIC_RAILS_ENGINE_PATH=../semantic-rails ./scripts/run_integration_tests.sh
```

The engine owns semantic contract fields and fingerprints. This adapter owns
its Python package, native SQLMesh graph checks, and binding schema. The private
`_contracts` module is an implementation detail of this adapter, not a shared
engine contract authority. Runtime checks remain engine-independent; only
optional authoring/export imports the public engine producer. Never add raw
Semantic Rails YAML parsing or hashing here. SQLMesh binding changes update:

- `src/sqlmesh_semantic_rails_contracts/_contracts.py`
- `src/sqlmesh_semantic_rails_contracts/exporter.py`
- `schemas/sqlmesh_binding.v1.json`
- `compatibility/baseline/v1/sqlmesh_binding.v1.json` only when establishing a
  new public binding major, never to make an incompatible same-major change pass
- `integration_tests/basic/semantic_rails_contract.yml`
- `tests/test_contract_v1.py`
- `scripts/run_integration_tests.sh`

Classify contract changes as `none`, `additive`, or `breaking`. Breaking changes
require a new binding major and dual-read support before emission changes.
Runtime validation and the published schemas must reject the same malformed v1
payloads. Add both schema-resolution and runtime tests for every changed field,
including duplicate and semantic-to-binding one-to-one invariants that JSON
Schema cannot express.

Before proposing a release, run:

```shell
python scripts/check_schema_compatibility.py
python scripts/verify_release_metadata.py
```

An exact candidate commit is required once the adapter declares an engine
lifecycle state. Required CI uses `engine.release_state`: `candidate` builds the
exact approved commit, while `released` requires the declared PyPI specifier
without a source fallback. An adapter release requires `released` and a public
engine tag that dereferences to the recorded commit.

Do not commit generated SQLMesh state, db files, logs, target directories, or
virtual environments.
