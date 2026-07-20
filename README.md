# SQLMesh Semantic Rails Contracts

`sqlmesh-semantic-rails-contracts` validates that SQLMesh project metadata still
satisfies the physical resource contract exported from a Semantic Rails
project. It checks model identity, columns, types, owner, tags, audits, kind,
gateway, and relation metadata without reimplementing the Semantic Rails
parser.

## Install

```shell
python -m pip install sqlmesh-semantic-rails-contracts
```

Contract generation also needs the engine-owned producer:

```shell
python -m pip install "sqlmesh-semantic-rails-contracts[export]"  # Python 3.11+
```

## Generate and check

```shell
semantic-rails-sqlmesh-contracts export \
  /path/to/semantic_rails_package \
  --sqlmesh-model-prefix analytics. \
  --owner analytics \
  --output semantic_rails_contract.yml

semantic-rails-sqlmesh-contracts check \
  --project-dir . \
  --contract-file semantic_rails_contract.yml
```

Use `--json` or the `report` command for the versioned
`ValidationReportV1` envelope:

```json
{
  "report_format_version": 1,
  "validator": {
    "name": "sqlmesh-semantic-rails-contracts",
    "version": "0.2.0"
  },
  "input": {
    "contract_format_version": 1,
    "binding_kind": "sqlmesh",
    "binding_version": 1,
    "legacy": false
  },
  "ok": true,
  "summary": {
    "package_count": 1,
    "resource_count": 2,
    "error_count": 0,
    "warning_count": 0,
    "sqlmesh_model_count": 2
  },
  "issues": []
}
```

## Contract ownership

The `semantic-rails` engine is the only producer of semantic resource facts and
the canonical semantic fingerprint. This package never parses or hashes raw
Semantic Rails YAML. It adds the independently versioned SQLMesh binding and
validates that binding against a loaded SQLMesh context.

See [CONTRACT_PAYLOAD_SPEC.md](CONTRACT_PAYLOAD_SPEC.md) and the schemas under
[`schemas/`](schemas/).

Canonical schema IDs resolve under
`https://semantic-rails.com/schemas/`. The wheel also carries the SQLMesh
schemas plus byte-identical copies of the engine-owned semantic-contract and
validation-report schemas under `sqlmesh_semantic_rails_contracts/schemas` for
offline registry use:

```python
from sqlmesh_semantic_rails_contracts import SCHEMA_NAMES, load_schema

schema_registry = {load_schema(name)["$id"]: load_schema(name) for name in SCHEMA_NAMES}
```

The v1 checker rejects:

- unsupported `contract_format_version`
- non-SQLMesh bindings
- unsupported `binding_version`
- duplicate packages or resources
- semantic packages or resources without exactly one SQLMesh binding
- binding packages or resources without exactly one semantic counterpart
- binding attempts to redefine engine-owned semantic columns
- schema-invalid or unknown fields in packages, resources, or columns

Legacy `packages:` payloads are read during the 0.2 migration window and emit
`LEGACY_CONTRACT_FORMAT` as a warning. New exports always use the split v1
contract; legacy read support is eligible for removal only in the next adapter
major.

## SQLMesh binding fields

Bindings may constrain:

- `sqlmesh_model`, `sqlmesh_project`, and `sqlmesh_gateway`
- `sqlmesh_kind` and `sqlmesh_external`
- `owner`, `tags`, and `audits`
- catalog, schema, identifier, and relation name
- severity, type checking, and extra-column policy

Short model names must resolve uniquely. Prefer fully qualified SQLMesh names.

## Matrix mode

Validate several projects or gateways:

```shell
semantic-rails-sqlmesh-contracts matrix \
  semantic_rails_sqlmesh_projects.yml \
  --output target/semantic_rails_sqlmesh_contract_matrix.json
```

## Compatibility

The distribution and the wire contracts have independent versions. An adapter
minor release may add support for additive semantic fields. A new contract or
binding major requires dual-read support before an engine starts emitting it.

CI tests SQLMesh `0.235.2` exactly as the oldest supported release and the
newest release allowed by the public specifier. A scheduled engine-main canary
is advisory; released engine artifacts remain authoritative.
[`compatibility.json`](compatibility.json) records the released dependency and
contract identities, and the immutable v1 baseline under
[`compatibility/baseline/v1/`](compatibility/baseline/v1/) gates incompatible
schema changes.

The release workflow verifies the approved public engine tag and commit, builds
the adapter wheel and sdist once, tests that exact wheel, publishes those same
bytes, and verifies their PyPI SHA-256 digests before creating a GitHub Release.
`release-provenance.json` records the exact adapter, engine, SQLMesh, schema,
source, and artifact identities for each release.

## Scope

This package validates SQLMesh metadata and physical columns against a
versioned Semantic Rails snapshot. It does not prove SQL equivalence and does
not replace SQLMesh plans or audits.
