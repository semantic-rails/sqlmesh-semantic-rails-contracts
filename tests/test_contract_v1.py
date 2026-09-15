from __future__ import annotations

import json
import os
from copy import deepcopy
from importlib import resources
from pathlib import Path

import jsonschema
import pytest
import yaml
from referencing import Registry, Resource

from sqlmesh_semantic_rails_contracts import SCHEMA_NAMES, load_schema
from sqlmesh_semantic_rails_contracts._contracts import contract_resources, load_contract_file
from sqlmesh_semantic_rails_contracts.checker import check_project

ROOT = Path(__file__).resolve().parent.parent


def _spec(name: str = "semantic_rails_contract.yml") -> dict:
    payload = yaml.safe_load((ROOT / "integration_tests" / "basic" / name).read_text())
    return dict(payload["semantic_rails_contracts"])


def _engine_contract_text(name: str) -> str:
    engine_path = os.environ.get("SEMANTIC_RAILS_ENGINE_PATH")
    if engine_path:
        schema_path = Path(engine_path) / "semantic_rails" / "contracts" / name
        if not schema_path.is_file():
            schema_path = Path(engine_path) / "schemas" / name
        return schema_path.read_text(encoding="utf-8")
    try:
        return resources.files("semantic_rails.contracts").joinpath(name).read_text(encoding="utf-8")
    except (ImportError, ModuleNotFoundError):
        pytest.skip("The exact semantic-rails candidate is not installed")


def _local_composed_validator() -> jsonschema.Draft202012Validator:
    semantic_schema = load_schema("semantic_contract.v1.json")
    binding_schema = load_schema("sqlmesh_binding.v1.json")
    composed_schema = load_schema("sqlmesh_contract.v1.json")
    registry = (
        Registry()
        .with_resource(semantic_schema["$id"], Resource.from_contents(semantic_schema))
        .with_resource(binding_schema["$id"], Resource.from_contents(binding_schema))
    )
    return jsonschema.Draft202012Validator(composed_schema, registry=registry)


def test_v1_contract_merges_engine_columns_into_sqlmesh_binding() -> None:
    issues, resources = contract_resources(_spec())

    assert not issues
    _local_composed_validator().validate(_spec())
    assert [resource.semantic_model_id for resource in resources] == ["customers", "orders"]
    assert [column["name"] for column in resources[0].columns] == [
        "customer_id",
        "customer_name",
    ]
    assert "columns" not in _spec()["binding"]["packages"][0]["resources"][0]


def test_v1_rejects_contract_and_binding_version_drift() -> None:
    wrong_contract = _spec()
    wrong_contract["contract_format_version"] = 2
    issues, _ = contract_resources(wrong_contract)
    assert {issue.code for issue in issues} == {"UNSUPPORTED_CONTRACT_FORMAT_VERSION"}

    wrong_binding = _spec()
    wrong_binding["binding"]["binding_version"] = 2
    issues, _ = contract_resources(wrong_binding)
    assert "UNSUPPORTED_BINDING_VERSION" in {issue.code for issue in issues}


def test_v1_requires_one_to_one_semantic_and_binding_resources() -> None:
    missing_binding = _spec()
    missing_binding["binding"]["packages"][0]["resources"].pop()

    issues, resources = contract_resources(missing_binding)

    assert "SQLMESH_BINDING_RESOURCE_NOT_FOUND" in {issue.code for issue in issues}
    assert [resource.semantic_model_id for resource in resources] == ["customers"]

    missing_semantic = _spec()
    missing_semantic["semantic"]["packages"][0]["resources"].pop()
    issues, _ = contract_resources(missing_semantic)
    assert "SEMANTIC_RESOURCE_NOT_FOUND" in {issue.code for issue in issues}


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda spec: spec["semantic"].pop("producer"), "INVALID_CONTRACT"),
        (
            lambda spec: spec["semantic"]["packages"][0].pop("package_schema_version"),
            "PACKAGE_SCHEMA_VERSION_REQUIRED",
        ),
        (
            lambda spec: spec["semantic"]["packages"][0].pop("semantic_hash"),
            "INVALID_SEMANTIC_PACKAGE",
        ),
        (
            lambda spec: spec["binding"]["packages"][0]["resources"][0].pop("sqlmesh_model"),
            "INVALID_BINDING_RESOURCE",
        ),
        (
            lambda spec: spec["binding"]["packages"][0]["resources"][0].update({"dbt_model": "customers"}),
            "INVALID_BINDING_RESOURCE",
        ),
        (
            lambda spec: spec["binding"]["packages"][0]["resources"][0].update({"tags": [""]}),
            "INVALID_BINDING_RESOURCE",
        ),
        (
            lambda spec: spec["binding"].update({"producer": None}),
            "INVALID_CONTRACT",
        ),
        (
            lambda spec: spec["binding"]["packages"][0].update({"policy": None}),
            "INVALID_BINDING_PACKAGE",
        ),
        (
            lambda spec: spec["binding"]["packages"][0].update({"accepted_semantic_hashes": None}),
            "INVALID_BINDING_PACKAGE",
        ),
        (
            lambda spec: spec["semantic"]["packages"][0].update({"namespace": None}),
            "INVALID_SEMANTIC_PACKAGE",
        ),
        (
            lambda spec: spec["semantic"]["packages"][0]["resources"][0].update({"relation": None}),
            "INVALID_SEMANTIC_RESOURCE",
        ),
        (
            lambda spec: spec["semantic"]["packages"][0]["resources"][0]["columns"][0].update({"data_type": None}),
            "INVALID_SEMANTIC_COLUMN",
        ),
        (
            lambda spec: spec.update({"unexpected": True}),
            "INVALID_CONTRACT",
        ),
    ],
)
def test_v1_runtime_rejects_schema_invalid_contracts(mutate, expected_code: str) -> None:
    spec = _spec()
    mutate(spec)

    issues, _ = contract_resources(spec)

    assert expected_code in {issue.code for issue in issues}
    with pytest.raises(jsonschema.ValidationError):
        _local_composed_validator().validate(spec)


def test_v1_rejects_duplicate_semantic_and_binding_resource_ids() -> None:
    duplicate_semantic = _spec()
    duplicate_semantic["semantic"]["packages"][0]["resources"].append(
        deepcopy(duplicate_semantic["semantic"]["packages"][0]["resources"][0])
    )
    issues, _ = contract_resources(duplicate_semantic)
    assert "DUPLICATE_SEMANTIC_RESOURCE" in {issue.code for issue in issues}

    duplicate_binding = _spec()
    duplicate_binding["binding"]["packages"][0]["resources"].append(
        deepcopy(duplicate_binding["binding"]["packages"][0]["resources"][0])
    )
    issues, _ = contract_resources(duplicate_binding)
    assert "DUPLICATE_BINDING_RESOURCE" in {issue.code for issue in issues}


def test_explicit_empty_contract_is_not_replaced_by_default_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sqlmesh_semantic_rails_contracts.checker.load_sqlmesh_snapshots",
        lambda *_args, **_kwargs: {},
    )

    report = check_project(project_dir=ROOT / "integration_tests" / "basic", contract={})

    assert report["ok"] is False
    assert report["summary"]["resource_count"] == 0
    assert {issue["code"] for issue in report["issues"]} == {"INVALID_CONTRACT"}


def test_explicit_null_contract_wrapper_is_rejected(tmp_path: Path) -> None:
    contract_file = tmp_path / "contract.yml"
    contract_file.write_text("semantic_rails_contracts: null\n", encoding="utf-8")

    with pytest.raises(ValueError, match="semantic_rails_contracts must be a mapping"):
        load_contract_file(contract_file)


def test_report_metadata_can_describe_unsupported_and_malformed_versions() -> None:
    from sqlmesh_semantic_rails_contracts._contracts import contract_metadata

    unsupported = _spec()
    unsupported["contract_format_version"] = 2
    assert contract_metadata(unsupported)["contract_format_version"] == 2

    malformed = _spec()
    malformed["contract_format_version"] = "future"
    malformed["binding"]["binding_version"] = True
    assert contract_metadata(malformed)["contract_format_version"] is None
    assert contract_metadata(malformed)["binding_version"] is None


def test_legacy_contracts_are_dual_read_with_a_migration_warning() -> None:
    issues, resources = contract_resources(
        {
            "packages": [
                {
                    "package_id": "legacy",
                    "models": [
                        {
                            "semantic_model_id": "customers",
                            "sqlmesh_model": "semantic_rails.customers",
                            "columns": [{"name": "customer_id"}],
                        }
                    ],
                }
            ]
        }
    )

    assert [resource.semantic_model_id for resource in resources] == ["customers"]
    assert {issue.code for issue in issues} == {"LEGACY_CONTRACT_FORMAT"}
    assert issues[0].to_dict()["severity"] == "warning"


def test_v1_rejects_binding_owned_columns() -> None:
    spec = _spec()
    spec["binding"]["packages"][0]["resources"][0]["columns"] = [{"name": "spoofed"}]

    issues, _ = contract_resources(spec)

    assert "INVALID_MODEL_CONTRACT" in {issue.code for issue in issues}


def test_binding_and_validation_report_schemas() -> None:
    spec = _spec()
    binding_schema = json.loads((ROOT / "schemas" / "sqlmesh_binding.v1.json").read_text())
    canonical_report_schema = json.loads((ROOT / "schemas" / "validation_report.v1.json").read_text())
    report_schema = json.loads((ROOT / "schemas" / "sqlmesh_validation_report.v1.json").read_text())
    registry = Registry().with_resource(
        canonical_report_schema["$id"],
        Resource.from_contents(canonical_report_schema),
    )
    for schema in (binding_schema, canonical_report_schema, report_schema):
        jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(binding_schema).validate(spec["binding"])

    report = check_project(
        project_dir=ROOT / "integration_tests" / "basic",
        contract=spec,
    )
    jsonschema.Draft202012Validator(canonical_report_schema).validate(report)
    jsonschema.Draft202012Validator(report_schema, registry=registry).validate(report)


def test_validation_report_uses_canonical_warning_severity() -> None:
    spec = _spec("semantic_rails_contract_failure.yml")
    spec["binding"]["packages"][0]["policy"]["severity"] = "warning"

    report = check_project(
        project_dir=ROOT / "integration_tests" / "basic",
        contract=spec,
    )

    assert report["ok"] is True
    assert report["summary"]["warning_count"] == 1
    assert report["issues"][0]["severity"] == "warning"


def test_canonical_engine_schema_accepts_composed_contract() -> None:
    semantic_text = _engine_contract_text("semantic_contract.v1.json")
    semantic_schema = json.loads(semantic_text)
    binding_schema = json.loads((ROOT / "schemas" / "sqlmesh_binding.v1.json").read_text())
    composed_schema = json.loads((ROOT / "schemas" / "sqlmesh_contract.v1.json").read_text())
    registry = (
        Registry()
        .with_resource(semantic_schema["$id"], Resource.from_contents(semantic_schema))
        .with_resource(binding_schema["$id"], Resource.from_contents(binding_schema))
    )
    for schema in (semantic_schema, binding_schema, composed_schema):
        jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(composed_schema, registry=registry).validate(_spec())


def test_vendored_engine_schemas_match_exact_candidate_bytes() -> None:
    for name in ("semantic_contract.v1.json", "validation_report.v1.json"):
        candidate = _engine_contract_text(name)
        vendored = (ROOT / "schemas" / name).read_text(encoding="utf-8")
        assert vendored == candidate
        assert json.loads(candidate)["$id"].startswith("https://semantic-rails.com/schemas/")


def test_packaged_schema_accessor_loads_complete_offline_registry() -> None:
    schemas = {name: load_schema(name) for name in SCHEMA_NAMES}
    assert set(schemas) == {
        "semantic_contract.v1.json",
        "sqlmesh_binding.v1.json",
        "sqlmesh_contract.v1.json",
        "sqlmesh_validation_report.v1.json",
        "validation_report.v1.json",
    }
    assert all(schema["$id"].startswith("https://semantic-rails.com/schemas/") for schema in schemas.values())


def test_engine_export_contains_only_physical_source_columns() -> None:
    from sqlmesh_semantic_rails_contracts.exporter import (
        SemanticRailsProducerUnavailable,
        export_semantic_contract,
    )

    try:
        payload = export_semantic_contract(ROOT / "integration_tests" / "semantic_rails_fixture")
    except SemanticRailsProducerUnavailable:
        pytest.skip("The optional semantic-rails producer is not installed")
    resources = {
        resource["semantic_model_id"]: resource
        for package in payload["semantic"]["packages"]
        for resource in package["resources"]
    }
    assert {column["name"] for column in resources["orders"]["columns"]} == {
        "customer_id",
        "order_id",
    }
    assert {column["name"] for column in resources["revenue"]["columns"]} == {
        "customer_id",
        "order_amount",
        "order_id",
        "ordered_at",
    }


def test_export_selects_matching_packages_and_rejects_missing_models(monkeypatch, capsys) -> None:
    from sqlmesh_semantic_rails_contracts import cli, exporter

    neutral = _spec()
    neutral.pop("binding")
    unselected = deepcopy(neutral["semantic"]["packages"][0])
    unselected["package_id"] = "unselected_package"
    unselected["resources"] = [{"semantic_model_id": "other", "columns": []}]
    neutral["semantic"]["packages"].append(unselected)
    monkeypatch.setattr(exporter, "export_semantic_contract", lambda _: deepcopy(neutral))

    assert cli.main(["export", ".", "--include-model", "customers"]) == 0
    payload = yaml.safe_load(capsys.readouterr().out)["semantic_rails_contracts"]
    assert [p["package_id"] for p in payload["semantic"]["packages"]] == ["semantic_fixture"]
    assert [p["package_id"] for p in payload["binding"]["packages"]] == ["semantic_fixture"]
    assert contract_resources(payload)[0] == []
    _local_composed_validator().validate(payload)
    with pytest.raises(ValueError, match="Included models were not found"):
        cli.main(["export", ".", "--include-model", "absent"])


def test_engine_metric_corpus_reaches_native_sqlmesh_graph(tmp_path) -> None:
    engine = pytest.importorskip("semantic_rails.contracts")
    from mf2sr.translate import translate

    from sqlmesh_semantic_rails_contracts.cli import main

    corpus = engine.load_contract_fixture("metric_portability.v1.json")
    source = tmp_path / "semantic_manifest.json"
    source.write_text(json.dumps(corpus["framework_input"]))
    imported = translate(source, tmp_path, package_id=corpus["package_id"], namespace=corpus["namespace"])
    portable = engine.export_metric_portability(imported.package_dir, import_provenance=imported.provenance)
    assert [row["id"] for row in portable["metrics"]] == corpus["expected_metric_ids"]
    output = tmp_path / "contract.yml"
    assert (
        main(
            ["export", str(imported.package_dir), "--sqlmesh-model-prefix", "semantic_rails.", "--output", str(output)]
        )
        == 0
    )
    bound = load_contract_file(output)
    assert bound["semantic"]["packages"][0]["semantic_hash"] == portable["package"]["semantic_hash"]
    report = check_project(project_dir=ROOT / "integration_tests/basic", contract=bound)
    assert report["ok"], report["issues"]
    # Native checking consumes only the validation/binding payload, with no
    # import of the portability producer or framework importer on that path.
    bound["semantic"]["packages"][0]["resources"][0]["columns"].append(
        {"name": "missing_governed_column", "required_by": corpus["expected_metric_ids"]}
    )
    rejected = check_project(project_dir=ROOT / "integration_tests/basic", contract=bound)
    assert not rejected["ok"]
    assert "SQLMESH_COLUMN_MISSING" in {row["code"] for row in rejected["issues"]}
