#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASIC_DIR="${ROOT_DIR}/integration_tests/basic"
FIXTURE_DIR="${ROOT_DIR}/integration_tests/semantic_rails_fixture"
EXPORT_OUTPUT="${ROOT_DIR}/target/exported_sqlmesh_contract.yml"
MATRIX_OUTPUT="${ROOT_DIR}/target/matrix_report.json"
MATRIX_FAILURE_OUTPUT="${ROOT_DIR}/target/matrix_failure_report.json"

if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run --with-editable "${ROOT_DIR}" python)
  CLI=(uv run --with-editable "${ROOT_DIR}" semantic-rails-sqlmesh-contracts)
  SQLMESH=(uv run --with-editable "${ROOT_DIR}" sqlmesh)
else
  PYTHON=(python)
  CLI=(semantic-rails-sqlmesh-contracts)
  SQLMESH=(sqlmesh)
fi

run_success() {
  local name="$1"
  shift
  echo "==> expect success: ${name}"
  "$@"
}

run_failure() {
  local name="$1"
  local expected_code="$2"
  shift 2
  echo "==> expect failure: ${name} (${expected_code})"
  local output
  set +e
  output="$("$@" 2>&1)"
  local status=$?
  set -e
  if [[ "${status}" -eq 0 ]]; then
    echo "Expected failure for ${name}, but command succeeded." >&2
    exit 1
  fi
  if [[ "${output}" != *"${expected_code}"* ]]; then
    echo "Expected ${expected_code} for ${name}, got:" >&2
    echo "${output}" >&2
    exit 1
  fi
}

mkdir -p "${ROOT_DIR}/target"

run_success "python compile" "${PYTHON[@]}" -m py_compile \
  "${ROOT_DIR}/src/semantic_rails_contracts_core/contracts.py" \
  "${ROOT_DIR}/src/semantic_rails_contracts_core/exporter.py" \
  "${ROOT_DIR}/src/sqlmesh_semantic_rails_contracts/checker.py" \
  "${ROOT_DIR}/src/sqlmesh_semantic_rails_contracts/cli.py" \
  "${ROOT_DIR}/src/sqlmesh_semantic_rails_contracts/exporter.py" \
  "${ROOT_DIR}/src/sqlmesh_semantic_rails_contracts/matrix.py" \
  "${ROOT_DIR}/src/sqlmesh_semantic_rails_contracts/sqlmesh_adapter.py"
run_success "cli help" "${CLI[@]}" --help
run_success "sqlmesh project info" "${SQLMESH[@]}" --paths "${BASIC_DIR}" info
run_success "export Semantic Rails fixture" "${CLI[@]}" export "${FIXTURE_DIR}" --sqlmesh-model-prefix semantic_rails. --sqlmesh-kind FULL --owner analytics --tag semantic_rails --output "${EXPORT_OUTPUT}"
grep -q "semantic_rails_contracts:" "${EXPORT_OUTPUT}"
grep -q "sqlmesh_model: semantic_rails.customers" "${EXPORT_OUTPUT}"
grep -q "name: order_amount" "${EXPORT_OUTPUT}"
grep -q "name: ordered_at" "${EXPORT_OUTPUT}"
if grep -q "name: SUM\\|name: DATE_TRUNC\\|name: month\\|name: COUNT\\|name: active" "${EXPORT_OUTPUT}"; then
  echo "Exporter leaked SQL function names or literals into required columns." >&2
  exit 1
fi
run_success "core expression and type checks" "${PYTHON[@]}" - <<'PY'
from pathlib import Path

from semantic_rails_contracts_core.contracts import types_match
from semantic_rails_contracts_core.exporter import columns_from_expr, iter_package_yaml_files, package_hash

assert columns_from_expr("SUM(order_amount)") == {"order_amount"}
assert columns_from_expr("COUNT(DISTINCT customer_id)") == {"customer_id"}
assert columns_from_expr("DATE_TRUNC('month', orders.ordered_at)") == {"ordered_at"}
assert columns_from_expr("CASE WHEN status = 'active' THEN order_amount ELSE 0 END") == {"status", "order_amount"}
assert types_match("varchar", "VARCHAR(255)", "compatible")
assert types_match("numeric", "DECIMAL(10, 2)", "compatible")
assert types_match("timestamp", "TIMESTAMP WITH TIME ZONE", "compatible")
assert not types_match("integer", "VARCHAR(255)", "compatible")

fixture = Path("integration_tests/semantic_rails_fixture")
assert any(path.suffix == ".yaml" for path in iter_package_yaml_files(fixture))
before = package_hash(fixture)
(fixture / "semantic_rails_contract.yml").write_text("generated: true\n", encoding="utf-8")
try:
    assert package_hash(fixture) == before
finally:
    (fixture / "semantic_rails_contract.yml").unlink()
PY
run_success "positive check" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file "${BASIC_DIR}/semantic_rails_contract.yml"
run_success "json report" "${CLI[@]}" report --project-dir "${BASIC_DIR}" --contract-file "${BASIC_DIR}/semantic_rails_contract.yml"
json_output="$("${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file "${BASIC_DIR}/semantic_rails_contract.yml" --json)"
printf '%s' "${json_output}" | "${PYTHON[@]}" -c 'import json, sys; data = json.load(sys.stdin); assert data["summary"]["resource_count"] == 2'
run_success "external model contract" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: raw_customers' '        sqlmesh_model: raw.customers' '        sqlmesh_kind: EXTERNAL' '        sqlmesh_external: true' '        columns: [{name: customer_id, data_type: integer}, {name: customer_name, data_type: text}]')
run_success "schema disambiguates short model name" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: customers' '        sqlmesh_schema: semantic_rails' '        columns: [{name: customer_id}]')
run_success "warn-only mode" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file "${BASIC_DIR}/semantic_rails_contract_failure.yml" --warn-only
run_success "matrix mode" "${CLI[@]}" matrix "${ROOT_DIR}/integration_tests/multi_project/matrix.yml" --output "${MATRIX_OUTPUT}"
grep -q '"project_count": 2' "${MATRIX_OUTPUT}"
grep -q '"failed_count": 0' "${MATRIX_OUTPUT}"
matrix_stdout="$("${CLI[@]}" matrix "${ROOT_DIR}/integration_tests/multi_project/matrix.yml" 2>"${ROOT_DIR}/target/matrix_no_output.stderr")"
printf '%s' "${matrix_stdout}" | "${PYTHON[@]}" -c 'import json, sys; data = json.load(sys.stdin); assert data["project_count"] == 2'
grep -q "Semantic Rails SQLMesh contract matrix passed" "${ROOT_DIR}/target/matrix_no_output.stderr"
warning_output="$("${CLI[@]}" matrix "${ROOT_DIR}/integration_tests/multi_project/matrix_warning.yml" --output "${ROOT_DIR}/target/matrix_warning_report.json")"
if [[ "${warning_output}" != *"with 1 warning(s)"* || "${warning_output}" != *"SQLMESH_COLUMN_MISSING"* ]]; then
  echo "Expected warning-only matrix details in console output, got:" >&2
  echo "${warning_output}" >&2
  exit 1
fi
grep -q '"warning_count": 1' "${ROOT_DIR}/target/matrix_warning_report.json"
run_failure "matrix drift" "SQLMESH_COLUMN_MISSING" "${CLI[@]}" matrix "${ROOT_DIR}/integration_tests/multi_project/matrix_failure.yml" --output "${MATRIX_FAILURE_OUTPUT}"
grep -q '"failed_count": 1' "${MATRIX_FAILURE_OUTPUT}"

run_failure "empty contract" "INVALID_CONTRACT" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file /dev/null
run_failure "hash mismatch" "SEMANTIC_HASH_NOT_ACCEPTED" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    semantic_hash: sha256:old' '    accepted_semantic_hashes: [sha256:new]' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        columns: [{name: customer_id}]')
run_failure "model not found" "SQLMESH_MODEL_NOT_FOUND" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: missing' '        sqlmesh_model: semantic_rails.missing' '        columns: [{name: customer_id}]')
run_failure "ambiguous short model" "SQLMESH_MODEL_AMBIGUOUS" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: customers' '        columns: [{name: customer_id}]')
run_failure "kind mismatch" "SQLMESH_KIND_MISMATCH" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        sqlmesh_kind: VIEW' '        columns: [{name: customer_id}]')
run_failure "external mismatch" "SQLMESH_EXTERNAL_MISMATCH" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: raw_customers' '        sqlmesh_model: raw.customers' '        sqlmesh_external: false' '        columns: [{name: customer_id}]')
run_failure "owner mismatch" "SQLMESH_OWNER_MISMATCH" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        owner: finance' '        columns: [{name: customer_id}]')
run_failure "relation metadata mismatch" "SQLMESH_RELATION_MISMATCH" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        sqlmesh_schema: wrong_schema' '        columns: [{name: customer_id}]')
run_failure "tag missing" "SQLMESH_TAG_MISSING" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        tags: [missing_tag]' '        columns: [{name: customer_id}]')
run_failure "audit missing" "SQLMESH_AUDIT_MISSING" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        audits: [missing_audit]' '        columns: [{name: customer_id}]')
run_failure "missing column" "SQLMESH_COLUMN_MISSING" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file "${BASIC_DIR}/semantic_rails_contract_failure.yml"
run_failure "json check failure" "SQLMESH_COLUMN_MISSING" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file "${BASIC_DIR}/semantic_rails_contract_failure.yml" --json
run_failure "exact type mismatch" "SQLMESH_COLUMN_TYPE_MISMATCH" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    policy: {type_check: exact}' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        columns: [{name: customer_id, data_type: bigint}]')
run_failure "extra column disallowed" "SQLMESH_COLUMN_EXTRA" "${CLI[@]}" check --project-dir "${BASIC_DIR}" --contract-file <(printf '%s\n' 'packages:' '  - package_id: semantic_fixture' '    policy: {allow_extra_columns: false}' '    models:' '      - semantic_model_id: customers' '        sqlmesh_model: semantic_rails.customers' '        columns: [{name: customer_id}]')

if command -v uv >/dev/null 2>&1; then
  run_success "package build" uv run --with-editable "${ROOT_DIR}" --with build python -m build "${ROOT_DIR}" --outdir "${ROOT_DIR}/target/dist"
else
  run_success "package build" "${PYTHON[@]}" -m build "${ROOT_DIR}" --outdir "${ROOT_DIR}/target/dist"
fi

echo "SQLMesh Semantic Rails contract integration matrix passed."
