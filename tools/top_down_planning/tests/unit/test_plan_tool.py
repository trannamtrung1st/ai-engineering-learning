from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.models import MarkActionableOperation
from top_down_planning.persistence import save_plan
from top_down_planning.plan_tool import (
    ENV_ELIGIBLE_IDS,
    ENV_PLAN_DIGEST,
    ENV_PLAN_FILE,
    ENV_SESSION_MODE,
    ENV_TXN_FILE,
    PlanToolError,
    SESSION_MODE_DISPOSITION,
    finalize,
    load_transaction,
    plan_tool_argv,
    record_operation,
    record_planning_state_update,
    record_update,
    reset_transaction,
    resolve_plan_tool_command,
    select_batch,
    status,
)
from top_down_planning.schema_docs import operation_examples
from typer.testing import CliRunner
from top_down_planning.plan_tool import app as plan_tool_app
from tests.plan_factory import make_root_plan


@pytest.fixture
def plan_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    plan = make_root_plan(
        input_file=str(tmp_path / "idea.md"),
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(output_dir, plan)
    txn_file = output_dir / ".planning-output" / "iterations" / "001-transaction.json"
    txn_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(ENV_TXN_FILE, str(txn_file))
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-001")
    monkeypatch.setenv(ENV_PLAN_FILE, str(output_dir / ".planning-output" / "plan.yaml"))
    monkeypatch.setenv(ENV_PLAN_DIGEST, "expected-digest")
    reset_transaction(txn_file)
    select_batch(node_id=["item-001"])
    return plan, txn_file


def test_record_and_finalize_transaction(plan_session) -> None:
    _, txn_file = plan_session
    record_operation(
        json_payload=json.dumps(
            {
                "type": "mark_actionable",
                "node_id": "item-001",
                "title": "Plan the requested work",
                "objective": "Produce the requested plan.",
                "expected_outputs": ["Plan"],
                "acceptance_criteria": ["Done"],
            }
        )
    )
    finalize()

    loaded = load_transaction(txn_file)
    assert len(loaded.operations) == 1
    assert isinstance(loaded.operations[0], MarkActionableOperation)


def test_finalize_requires_at_least_one_operation(plan_session) -> None:
    with pytest.raises(
        PlanToolError,
        match="at least one operation, update, or planning state update",
    ):
        finalize()


def test_finalize_and_load_state_only_transaction(plan_session) -> None:
    _, txn_file = plan_session
    reset_transaction(txn_file)
    record_planning_state_update(
        json_payload=json.dumps(
            {
                "finding_dispositions": [
                    {
                        "finding_id": "dep-001",
                        "disposition": "accepted",
                        "rationale": "Valid dependency fix",
                    }
                ]
            }
        )
    )
    finalize()

    loaded = load_transaction(txn_file)
    assert loaded.operations == []
    assert loaded.planning_state_update is not None
    assert len(loaded.planning_state_update.finding_dispositions) == 1
    assert loaded.planning_state_update.finding_dispositions[0].finding_id == "dep-001"


def test_load_transaction_rejects_empty_transaction(tmp_path: Path) -> None:
    txn_file = tmp_path / "empty-transaction.json"
    txn_file.write_text(
        json.dumps({"operations": [], "plan_digest": "abc"}),
        encoding="utf-8",
    )
    with pytest.raises(PlanToolError, match="no operations, updates, or state update"):
        load_transaction(txn_file)


def test_record_operation_requires_select_batch(
    plan_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, txn_file = plan_session
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-001")
    with pytest.raises(PlanToolError, match="select-batch"):
        record_operation(
            json_payload=json.dumps(
                {
                    "type": "mark_actionable",
                    "node_id": "item-001",
                    "title": "Plan the requested work",
                    "objective": "Produce the requested plan.",
                    "expected_outputs": ["Plan"],
                    "acceptance_criteria": ["Done"],
                }
            )
        )


def test_select_batch_records_scope(plan_session) -> None:
    _, txn_file = plan_session
    reset_transaction(txn_file)
    select_batch(node_id=["item-001"], purpose="Expand root")
    draft_path = txn_file.with_suffix(txn_file.suffix + ".draft")
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["selected_items"] == ["item-001"]
    assert draft["batch_purpose"] == "Expand root"


def test_select_batch_rejects_ineligible_node(
    plan_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from top_down_planning.models import PlanItem
    from top_down_planning.persistence import save_plan

    plan, txn_file = plan_session
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id=None,
            title="Sibling",
            objective="sibling",
            depth=0,
            order=2,
        )
    )
    output_dir = txn_file.parent.parent.parent
    save_plan(output_dir, plan)
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-001")
    with pytest.raises(PlanToolError, match="not in the eligible"):
        select_batch(node_id=["item-002"])


def test_finalize_requires_all_selected_operations(
    plan_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from top_down_planning.models import PlanItem
    from top_down_planning.persistence import save_plan

    plan, txn_file = plan_session
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id=None,
            title="Sibling",
            objective="sibling",
            depth=0,
            order=2,
        )
    )
    output_dir = txn_file.parent.parent.parent
    save_plan(output_dir, plan)
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-001,item-002")
    select_batch(node_id=["item-001", "item-002"])
    record_operation(
        json_payload=json.dumps(
            {
                "type": "mark_actionable",
                "node_id": "item-001",
                "title": "Plan the requested work",
                "objective": "Produce the requested plan.",
                "expected_outputs": ["Plan"],
                "acceptance_criteria": ["Done"],
            }
        )
    )
    with pytest.raises(PlanToolError, match="missing operations"):
        finalize()
    assert not txn_file.is_file()


def test_rejects_unselected_node(plan_session) -> None:
    with pytest.raises(PlanToolError, match="selected items"):
        record_operation(
            json_payload=json.dumps(
                {
                    "type": "mark_actionable",
                    "node_id": "item-999",
                    "expected_outputs": ["x"],
                    "acceptance_criteria": ["y"],
                }
            )
        )


def test_status_reports_missing_nodes(plan_session, capsys) -> None:
    record_operation(
        json_payload=json.dumps(
            {
                "type": "mark_actionable",
                "node_id": "item-001",
                "title": "Plan the requested work",
                "objective": "Produce the requested plan.",
                "expected_outputs": ["Plan"],
                "acceptance_criteria": ["Done"],
            }
        )
    )
    status()
    captured = capsys.readouterr().out
    payload = json.loads(captured[captured.index("{") :])
    assert payload["missing_node_ids"] == []
    assert payload["recorded_operations"] == 1


def test_resolve_plan_tool_command_prefers_explicit() -> None:
    assert resolve_plan_tool_command(explicit="custom-plan-tool") == "custom-plan-tool"


def test_plan_tool_argv_splits_shell_command() -> None:
    argv = plan_tool_argv("python -m top_down_planning.plan_tool", "status")
    assert argv[:3] == ["python", "-m", "top_down_planning.plan_tool"]
    assert argv[-1] == "status"


def test_reset_transaction_clears_draft_and_final(tmp_path: Path, plan_session) -> None:
    _, txn_file = plan_session
    record_operation(
        json_payload=json.dumps(
            {
                "type": "mark_actionable",
                "node_id": "item-001",
                "title": "Plan the requested work",
                "objective": "Produce the requested plan.",
                "expected_outputs": ["Plan"],
                "acceptance_criteria": ["Done"],
            }
        )
    )
    finalize()
    assert txn_file.is_file()
    reset_transaction(txn_file)
    assert not txn_file.is_file()
    assert not txn_file.with_suffix(txn_file.suffix + ".draft").is_file()


def test_plan_tool_discovery_commands_offline() -> None:
    runner = CliRunner()
    usage = runner.invoke(plan_tool_app, ["usage"])
    assert usage.exit_code == 0
    assert "planning-plan-tool schema" in usage.stdout

    schema = runner.invoke(plan_tool_app, ["schema", "--target", "operation"])
    assert schema.exit_code == 0
    assert '"properties"' in schema.stdout

    example_payload = operation_examples()["mark_actionable"]
    validate = runner.invoke(
        plan_tool_app,
        ["validate", "--json", json.dumps(example_payload)],
    )
    assert validate.exit_code == 0
    assert "Valid planning operation." in validate.stdout


def test_finalize_and_load_updates_only_transaction(
    plan_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, txn_file = plan_session
    plan.plan.append(
        make_root_plan(
            input_file="idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ).plan[0].model_copy(
            update={
                "id": "item-002",
                "parent_id": "item-001",
                "title": "Child",
                "objective": "child",
                "depth": 1,
                "order": 2,
            }
        )
    )
    output_dir = txn_file.parent.parent.parent
    save_plan(output_dir, plan)
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-002")
    select_batch(node_id=["item-002"])
    record_update(
        json_payload=json.dumps(
            {
                "type": "update_item",
                "node_id": "item-001",
                "reason": "Align parent notes.",
                "notes": ["updated"],
            }
        )
    )
    finalize()

    loaded = load_transaction(txn_file)
    assert loaded.operations == []
    assert len(loaded.updates) == 1
    assert loaded.planning_state_update is None


def test_record_update_and_finalize(plan_session, monkeypatch: pytest.MonkeyPatch) -> None:
    plan, txn_file = plan_session
    plan.plan.append(
        make_root_plan(
            input_file="idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ).plan[0].model_copy(
            update={
                "id": "item-002",
                "parent_id": "item-001",
                "title": "Child",
                "objective": "child",
                "depth": 1,
                "order": 2,
            }
        )
    )
    from top_down_planning.persistence import save_plan

    output_dir = txn_file.parent.parent.parent
    save_plan(output_dir, plan)
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-002")
    select_batch(node_id=["item-002"])
    record_operation(
        json_payload=json.dumps(
            {
                "type": "expand",
                "node_id": "item-002",
                "children": [{"title": "Slice", "objective": "slice"}],
            }
        )
    )
    record_update(
        json_payload=json.dumps(
            {
                "type": "update_item",
                "node_id": "item-001",
                "reason": "Align parent notes.",
                "notes": ["updated"],
            }
        )
    )
    finalize()
    loaded = load_transaction(txn_file)
    assert len(loaded.updates) == 1
    assert loaded.updates[0].node_id == "item-001"


def test_record_operation_rejects_existing_finalized_transaction(
    plan_session,
) -> None:
    _, txn_file = plan_session
    record_operation(
        json_payload=json.dumps(
            {
                "type": "mark_actionable",
                "node_id": "item-001",
                "title": "Plan the requested work",
                "objective": "Produce the requested plan.",
                "expected_outputs": ["Plan"],
                "acceptance_criteria": ["Done"],
            }
        )
    )
    finalize()
    with pytest.raises(PlanToolError, match="finalized transaction already exists"):
        record_operation(
            json_payload=json.dumps(
                {
                    "type": "mark_actionable",
                    "node_id": "item-001",
                    "title": "Again",
                    "objective": "Again",
                    "expected_outputs": ["Plan"],
                    "acceptance_criteria": ["Done"],
                }
            )
        )


def test_disposition_record_update_without_select_batch(
    plan_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, txn_file = plan_session
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_SESSION_MODE, SESSION_MODE_DISPOSITION)
    record_update(
        json_payload=json.dumps(
            {
                "type": "update_item",
                "node_id": "item-001",
                "reason": "Accepted reviewer finding.",
                "notes": ["updated"],
            }
        )
    )
    finalize()
    loaded = load_transaction(txn_file)
    assert len(loaded.updates) == 1


def test_disposition_rejects_select_batch(
    plan_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, txn_file = plan_session
    reset_transaction(txn_file)
    monkeypatch.setenv(ENV_SESSION_MODE, SESSION_MODE_DISPOSITION)
    with pytest.raises(PlanToolError, match="Disposition sessions do not support select-batch"):
        select_batch(node_id=["item-001"])


def test_record_update_rejects_selected_node(plan_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ELIGIBLE_IDS, "item-001")
    with pytest.raises(PlanToolError, match="must not be an assigned item"):
        record_update(
            json_payload=json.dumps(
                {
                    "type": "update_item",
                    "node_id": "item-001",
                    "reason": "bad",
                    "notes": ["x"],
                }
            )
        )
