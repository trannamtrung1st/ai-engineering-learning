"""Plan schema v2: risks, source_refs, and v2-only load contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem, PLAN_SCHEMA_VERSION
from top_down_planning.domain.plan_schema import (
    UNSUPPORTED_PLAN_SCHEMA_MESSAGE,
    UnsupportedPlanSchemaVersionError,
    validate_plan_schema_version,
)
from top_down_planning.domain.validators import validate_plan
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _minimal_plan_dict(**overrides: object) -> dict:
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "id": "plan-v2",
        "revision": 1,
        "output_goal": "Deliver the output.",
        "input_refs": [],
        "scope": {"includes": [], "excludes": []},
        "boundaries": [],
        "constraints": [],
        "assumptions": [],
        "acceptance": [],
        "risks": [],
        "items": [
            {
                "id": "item-root",
                "parent_id": None,
                "order_key": "0000000000",
                "depth": 0,
                "title": "Root",
                "kind": "aggregate",
                "risks": [],
                "source_refs": [],
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_plan_schema_version_is_two() -> None:
    assert PLAN_SCHEMA_VERSION == 2


@pytest.mark.parametrize("schema_version", [1, 99])
def test_validate_plan_schema_version_rejects_unsupported(schema_version: int) -> None:
    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run"):
        validate_plan_schema_version(_minimal_plan_dict(schema_version=schema_version))


def test_validate_plan_schema_version_rejects_missing() -> None:
    payload = _minimal_plan_dict()
    del payload["schema_version"]

    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run"):
        validate_plan_schema_version(payload)


def test_validate_plan_schema_version_rejects_corrupt_type() -> None:
    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run"):
        validate_plan_schema_version(_minimal_plan_dict(schema_version="2"))


def test_plan_from_dict_rejects_schema_version_one() -> None:
    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run"):
        Plan.from_dict(_minimal_plan_dict(schema_version=1))


def test_plan_from_dict_rejects_missing_schema_version() -> None:
    payload = _minimal_plan_dict()
    del payload["schema_version"]

    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run"):
        Plan.from_dict(payload)


def test_file_store_rejects_unsupported_plan_schema_version(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-gate",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )
    run_id = "run-20260101T000901-000901"
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config()),
    )
    plan_path = store.run_dir(run_id) / "plan.json"
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_payload["schema_version"] = 1
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run") as exc_info:
        store.load_plan(run_id)

    assert exc_info.value.code == "unsupported_plan_schema"
    assert exc_info.value.args[0] == UNSUPPORTED_PLAN_SCHEMA_MESSAGE


def test_plan_from_dict_defaults_missing_v2_list_fields() -> None:
    payload = _minimal_plan_dict()
    del payload["risks"]
    del payload["items"][0]["source_refs"]

    plan = Plan.from_dict(payload)

    assert plan.risks == []
    assert plan.items["item-root"].source_refs == []


def test_plan_from_dict_treats_null_risks_as_empty_list() -> None:
    payload = _minimal_plan_dict(risks=None)
    payload["items"][0]["risks"] = None

    plan = Plan.from_dict(payload)

    assert plan.risks == []
    assert plan.items["item-root"].risks == []


def test_plan_round_trip_preserves_risks_and_source_refs() -> None:
    plan = Plan(
        id="plan-round",
        revision=3,
        output_goal="Goal.",
        risks=["Cross-cutting delivery risk."],
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000000",
                title="Work",
                kind="work",
                risks=["Off-by-one in index adjustment."],
                source_refs=["spec.md → Multiple tabs"],
            ),
        },
    )
    restored = Plan.from_dict(plan.to_dict())

    assert restored.schema_version == 2
    assert restored.risks == ["Cross-cutting delivery risk."]
    assert restored.items["item-work"].risks == ["Off-by-one in index adjustment."]
    assert restored.items["item-work"].source_refs == ["spec.md → Multiple tabs"]


def test_empty_risk_entry_fails_validation() -> None:
    plan = Plan(
        id="plan-bad-risk",
        revision=0,
        output_goal="Goal.",
        risks=["valid risk"],
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
                risks=["  "],
            )
        },
    )

    result = validate_plan(plan)
    assert not result.ok
    assert any(
        issue.path == ["item-root", "risks", "0"]
        and "non-empty strings" in issue.message
        for issue in result.issues
    )


def test_empty_source_ref_entry_fails_validation() -> None:
    plan = Plan(
        id="plan-bad-ref",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="work",
                source_refs=[""],
            )
        },
    )

    result = validate_plan(plan)
    assert not result.ok
    assert any(
        issue.path == ["item-root", "source_refs", "0"]
        for issue in result.issues
    )


def test_empty_plan_risk_entry_fails_validation() -> None:
    plan = Plan(
        id="plan-bad-plan-risk",
        revision=0,
        output_goal="Goal.",
        risks=[""],
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )

    result = validate_plan(plan)
    assert not result.ok
    assert any(issue.path == ["plan", "risks", "0"] for issue in result.issues)


def test_non_list_plan_risks_emits_single_list_type_issue() -> None:
    plan = Plan(
        id="plan-bad-type",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )
    plan.risks = "not-a-list"  # type: ignore[assignment]

    result = validate_plan(plan)
    list_issues = [
        issue
        for issue in result.issues
        if issue.path == ["plan", "risks"] and "must be a list" in issue.message
    ]
    assert len(list_issues) == 1


def test_in_memory_invalid_schema_version_fails_validation() -> None:
    plan = Plan.from_dict(_minimal_plan_dict())
    plan.schema_version = 99

    result = validate_plan(plan)
    assert not result.ok
    assert any(issue.code == "invalid_schema_version" for issue in result.issues)


def test_canonical_plan_payload_rejects_in_memory_wrong_schema_version() -> None:
    from top_down_planning.persistence.file_store import _canonical_plan_payload

    plan = Plan.from_dict(_minimal_plan_dict())
    plan.schema_version = 99

    with pytest.raises(UnsupportedPlanSchemaVersionError, match="Recreate the run"):
        _canonical_plan_payload(plan)
