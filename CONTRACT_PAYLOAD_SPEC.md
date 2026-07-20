# SQLMesh Binding Contract

This repository does not own the Semantic Rails semantic contract. The
canonical `contract_format_version: 1` schema, fingerprint algorithm, and
semantic producer are released by the public `semantic-rails` engine as:

```text
https://semantic-rails.com/schemas/semantic_contract.v1.json
```

This package owns only the SQLMesh binding:

- [`schemas/sqlmesh_binding.v1.json`](schemas/sqlmesh_binding.v1.json)
- [`schemas/sqlmesh_contract.v1.json`](schemas/sqlmesh_contract.v1.json)
- [`schemas/sqlmesh_validation_report.v1.json`](schemas/sqlmesh_validation_report.v1.json)

Generated payloads contain independently versioned `semantic` and `binding`
sections. SQLMesh-only fields can therefore evolve without changing the
engine-owned semantic contract.

Every v1 SQLMesh payload has exactly one binding package for each semantic
package and exactly one binding resource for each semantic resource. JSON
Schema validates each section's shape; the runtime enforces these cross-section
identity and uniqueness invariants. Binding resources may reference semantic
columns but may never redefine them.

```yaml
semantic_rails_contracts:
  contract_format_version: 1
  semantic:
    producer: {name: semantic-rails, version: 0.2.0}
    packages:
      - package_id: analytics
        package_schema_version: 1
        semantic_hash: sha256:...
        resources:
          - semantic_model_id: orders
            columns:
              - name: order_id
                required_by: [entity.order]
  binding:
    kind: sqlmesh
    binding_version: 1
    packages:
      - package_id: analytics
        accepted_semantic_hashes: [sha256:...]
        policy:
          severity: error
          type_check: compatible
        resources:
          - semantic_model_id: orders
            sqlmesh_model: analytics.orders
            owner: analytics
```

The checker rejects unsupported contract or binding majors. Legacy `packages:`
payloads remain readable during the 0.2 transition with a
`LEGACY_CONTRACT_FORMAT` warning, but the exporter emits only the v1 split
format. Removing that reader is a future adapter-major change.

The common report envelope is engine-owned at
`https://semantic-rails.com/schemas/validation_report.v1.json`. The SQLMesh
report schema composes that canonical envelope and adds only the SQLMesh
validator identity and `summary.sqlmesh_model_count`.
