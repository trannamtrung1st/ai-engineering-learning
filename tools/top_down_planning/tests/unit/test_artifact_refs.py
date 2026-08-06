"""Unit tests for structured artifact references."""

from __future__ import annotations

import pytest

from top_down_planning.domain.artifact_refs import (
    OutputRecordRef,
    PlanItemFieldRef,
    artifact_ref_canonical_key,
    artifact_ref_to_dict,
    artifact_refs_equal,
    digest_field_value,
    parse_artifact_ref,
    parse_artifact_ref_list,
    validate_artifact_ref_kinds,
    validate_artifact_ref_within_scope,
)


def test_output_record_ref_round_trip() -> None:
    ref = OutputRecordRef(
        kind="output_record",
        record_kind="evidence",
        record_key="evidence-01",
        field="summary",
        value_digest=digest_field_value("artifact added"),
    )
    payload = artifact_ref_to_dict(ref)
    parsed = parse_artifact_ref(payload)
    assert isinstance(parsed, OutputRecordRef)
    assert artifact_refs_equal(ref, parsed)
    assert artifact_ref_canonical_key(ref) == artifact_ref_canonical_key(parsed)


def test_output_record_ref_minimal_fields() -> None:
    ref = parse_artifact_ref(
        {
            "kind": "output_record",
            "record_kind": "batch",
            "record_key": "batch-01",
        }
    )
    assert isinstance(ref, OutputRecordRef)
    assert ref.field is None
    assert ref.value_digest is None
    assert artifact_ref_to_dict(ref) == {
        "kind": "output_record",
        "record_kind": "batch",
        "record_key": "batch-01",
    }


def test_output_record_ref_requires_record_kind_and_key() -> None:
    with pytest.raises(ValueError, match="record_key"):
        parse_artifact_ref({"kind": "output_record", "record_kind": "output"})


def test_parse_artifact_ref_list_rejects_non_objects() -> None:
    with pytest.raises(ValueError, match="artifact refs\\[1\\] must be an object"):
        parse_artifact_ref_list(
            [
                {
                    "kind": "output_record",
                    "record_kind": "contribution",
                    "record_key": "contrib-01",
                },
                "ignored",
            ]
        )


def test_validate_artifact_ref_kinds_allows_output_record() -> None:
    ref = parse_artifact_ref(
        {
            "kind": "output_record",
            "record_kind": "disposition",
            "record_key": "item-leaf",
        }
    )
    validate_artifact_ref_kinds(
        [ref],
        frozenset({"output_path", "output_record"}),
        context="whole_output test",
    )


def test_validate_artifact_ref_within_scope_accepts_in_scope_plan_ref() -> None:
    ref = PlanItemFieldRef(
        kind="plan_item_field",
        item_id="item-api",
        field="acceptance",
        value_digest=digest_field_value("checks"),
    )
    validate_artifact_ref_within_scope(
        ref,
        allowed_item_ids={"item-api"},
        allowed_kinds=frozenset({"plan_item_field", "plan_dependency"}),
        context="test",
    )


def test_validate_artifact_ref_within_scope_rejects_out_of_scope_item() -> None:
    ref = PlanItemFieldRef(
        kind="plan_item_field",
        item_id="item-other",
        field="acceptance",
        value_digest=digest_field_value("checks"),
    )
    with pytest.raises(ValueError, match="outside declared scope"):
        validate_artifact_ref_within_scope(
            ref,
            allowed_item_ids={"item-api"},
            allowed_kinds=frozenset({"plan_item_field"}),
            context="test",
        )
