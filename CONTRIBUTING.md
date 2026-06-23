# Contributing

Run the full local matrix before opening a change:

```shell
./scripts/run_integration_tests.sh
```

Keep the SQLMesh package contract payload shape aligned with the dbt package.
When adding a new field, update:

- `src/semantic_rails_contracts_core/contracts.py`
- `src/sqlmesh_semantic_rails_contracts/exporter.py`
- `README.md`
- `integration_tests/basic/semantic_rails_contract.yml`
- `scripts/run_integration_tests.sh`

Do not commit generated SQLMesh state, db files, logs, target directories, or
virtual environments.
