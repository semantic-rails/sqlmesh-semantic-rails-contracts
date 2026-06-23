# SQLMesh Semantic Rails Contracts

`sqlmesh-semantic-rails-contracts` checks that SQLMesh project metadata still
satisfies the model, column, owner, tag, audit, relation, and package-hash
contracts exported from a Semantic Rails package.

It is the SQLMesh counterpart to `dbt-semantic-rails-contracts`, but it is not a
macro package. SQLMesh projects are Python-addressable, support gateways, and
already have native plan/audit concepts, so this package ships as an installable
Python CLI:

```shell
semantic-rails-sqlmesh-contracts check \
  --project-dir . \
  --contract-file semantic_rails_contract.yml
```

## Install

Local development:

```shell
python -m pip install -e .
```

Future public install:

```shell
python -m pip install sqlmesh-semantic-rails-contracts
```

## Contract Shape

The SQLMesh checker accepts the same top-level payload shape as the dbt package:
see [CONTRACT_PAYLOAD_SPEC.md](CONTRACT_PAYLOAD_SPEC.md) for the cross-package
schema and compatibility rules.

```yaml
semantic_rails_contracts:
  packages:
    - package_id: jaffle_shop
      namespace: jaffle
      contract_version: 1
      semantic_hash: sha256:...
      accepted_semantic_hashes:
        - sha256:...
      policy:
        severity: error
        type_check: compatible
        allow_extra_columns: true
        require_owner: true
        require_audits: true
      models:
        - semantic_model_id: customers
          sqlmesh_model: semantic_rails.customers
          sqlmesh_kind: FULL
          owner: analytics
          tags: [semantic_rails, public]
          audits: [not_null_customer_id]
          columns:
            - name: customer_id
              data_type: integer
              required_by: ["entity.customer"]
            - name: customer_name
              data_type: text
              required_by: ["dimension.customer_name"]
```

Supported SQLMesh-specific fields:

- `sqlmesh_model`: SQLMesh model name, preferably fully qualified
- `sqlmesh_project`: expected SQLMesh model project metadata
- `sqlmesh_gateway`: expected gateway when checking a gateway-specific project
- `sqlmesh_kind`: expected SQLMesh model kind such as `FULL`, `VIEW`, or `SEED`
- `sqlmesh_external` / `external`: expected boolean for SQLMesh external models
- `owner`: expected SQLMesh owner metadata
- `tags` / `sqlmesh_tags`: required SQLMesh tags
- `audits` / `sqlmesh_audits`: required SQLMesh audits
- `sqlmesh_catalog`, `sqlmesh_schema`, `sqlmesh_identifier`,
  `sqlmesh_relation_name`: optional relation metadata checks

The checker also accepts `dbt_model` as a compatibility fallback for model name,
but SQLMesh projects should prefer `sqlmesh_model` in committed contracts.
Short model names are allowed only when they resolve to one SQLMesh model. If
two schemas both define `customers`, use a fully qualified name such as
`semantic_rails.customers` to avoid `SQLMESH_MODEL_AMBIGUOUS`.

For CI systems that want machine-readable output and an exit code, use:

```shell
semantic-rails-sqlmesh-contracts check \
  --project-dir . \
  --contract-file semantic_rails_contract.yml \
  --json
```

## Export From Semantic Rails YAML

```shell
semantic-rails-sqlmesh-contracts export /path/to/semantic_rails_package \
  --sqlmesh-model-prefix semantic_rails. \
  --sqlmesh-kind FULL \
  --owner analytics \
  --tag semantic_rails \
  --output semantic_rails_contract.yml
```

The exporter uses the same Semantic Rails YAML traversal and required-column
extraction logic as the dbt package. The intent is for this core extraction
logic to live in a small shared package that both public repos can depend on.

## Matrix Mode

SQLMesh supports gateways, so Semantic Rails can validate several connector
contexts without pretending they belong to one physical project:

```yaml
version: 1

defaults:
  project_dir: .

projects:
  - name: duckdb_local
    gateway: duckdb
    contract_file: semantic_rails_contract.yml

  - name: snowflake_prod
    project_dir: ../sqlmesh-snowflake
    gateway: snowflake
    contract_file: semantic_rails_contract.yml
```

Run:

```shell
semantic-rails-sqlmesh-contracts matrix semantic_rails_sqlmesh_projects.yml \
  --output target/semantic_rails_sqlmesh_contract_matrix.json
```

## Error Codes

- `INVALID_CONTRACT`: missing or malformed contract payload
- `INVALID_MODEL_CONTRACT`: malformed resource entry
- `SEMANTIC_HASH_NOT_ACCEPTED`: Semantic Rails hash is outside the allowed set
- `SQLMESH_MODEL_NOT_FOUND`: expected SQLMesh model is absent
- `SQLMESH_MODEL_AMBIGUOUS`: model name matched multiple SQLMesh models
- `SQLMESH_PROJECT_MISMATCH`: project metadata differs
- `SQLMESH_GATEWAY_MISMATCH`: gateway metadata differs
- `SQLMESH_KIND_MISMATCH`: model kind differs
- `SQLMESH_EXTERNAL_MISMATCH`: external-model expectation differs
- `SQLMESH_OWNER_MISMATCH`: owner differs
- `SQLMESH_OWNER_MISSING`: owner is required but absent
- `SQLMESH_TAG_MISSING`: required tag is absent
- `SQLMESH_AUDIT_MISSING`: required audit is absent
- `SQLMESH_RELATION_MISMATCH`: catalog/schema/identifier/relation differs
- `SQLMESH_COLUMN_MISSING`: required column is absent
- `SQLMESH_COLUMN_TYPE_MISMATCH`: optional type check failed
- `SQLMESH_COLUMN_EXTRA`: `allow_extra_columns: false` and SQLMesh declares an unlisted column

## Verification

```shell
./scripts/run_integration_tests.sh
```

The integration matrix installs the package, validates a SQLMesh DuckDB project,
runs positive and negative contract checks, verifies exporter output, verifies
matrix mode, and builds the package distribution.

## Scope And Limits

This package validates SQLMesh metadata and model column contracts against a
versioned Semantic Rails snapshot. It does not prove that SQLMesh SQL is
semantically equivalent to Semantic Rails query execution, and it does not
replace SQLMesh plans or audits. Use it as a CI gate between Semantic Rails
semantic model ownership and SQLMesh physical model implementation.
