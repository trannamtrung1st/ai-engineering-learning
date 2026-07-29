from pathlib import Path

import pytest

from top_down_planning.config_loader import merge_run_options
from top_down_planning.digest import compute_plan_digest
from top_down_planning.generation_context import (
    build_plan_overview,
    ensure_plan_overview_artifact,
    prepare_batch_context,
    select_patchable_node_ids,
    select_relevant_node_ids,
)
from top_down_planning.models import (
    BatchStrategy,
    DecompositionStatus,
    GenerationConfig,
    MarkActionableOperation,
    PlanItem,
    PlanningLimits,
    WholePlanContextMode,
)
from top_down_planning.plan_tool import (
    ENV_PLAN_DIGEST,
    ENV_PLAN_FILE,
    ENV_SELECTED_IDS,
    ENV_TXN_FILE,
    PlanToolError,
    finalize,
    record_operation,
    reset_transaction,
)
from top_down_planning.scheduler import select_concurrent_batches
from top_down_planning.validator import validate_wave_responses
from tests.helpers import default_generation, make_agent_response
from tests.plan_factory import make_root_plan


def _plan_with_branches():
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="Produce a plan",
        input_digest="a",
        output_goal_digest="b",
    )
    plan.plan.extend(
        [
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Branch A",
                objective="Workstream A",
                depth=1,
                order=2,
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Branch B",
                objective="Workstream B",
                depth=1,
                order=3,
            ),
            PlanItem(
                id="item-004",
                parent_id="item-002",
                title="Nested task",
                objective="Detail A",
                depth=2,
                order=4,
            ),
        ]
    )
    return plan


def test_plan_overview_is_deterministic_for_same_digest() -> None:
    plan = _plan_with_branches()
    digest = compute_plan_digest(plan)
    first = build_plan_overview(plan, digest)
    second = build_plan_overview(plan, digest)
    assert first == second
    assert digest in first
    assert "Branch A" in first


def test_select_relevant_context_includes_ancestors_and_siblings() -> None:
    plan = _plan_with_branches()
    relevant = select_relevant_node_ids(plan, {"item-004"})
    assert "item-001" in relevant
    assert "item-002" in relevant
    assert "item-003" in relevant
    assert "item-004" not in relevant


def test_select_patchable_context_matches_direct_relations() -> None:
    plan = _plan_with_branches()
    patchable = select_patchable_node_ids(plan, {"item-004"})
    assert patchable == {"item-001", "item-002"}


def test_prepare_batch_context_omits_patchable_section_for_amend(tmp_path: Path) -> None:
    plan = _plan_with_branches()
    digest = compute_plan_digest(plan)
    output_dir = tmp_path / "planning-output"
    item = plan.item_by_id("item-002")
    assert item is not None
    prepared = prepare_batch_context(
        plan=plan,
        selected_items=[item],
        plan_digest=digest,
        output_dir=output_dir,
        whole_plan_context=WholePlanContextMode.HYBRID,
        max_context_characters=30000,
        include_cross_item_updates=False,
    )
    assert "Patchable related items" not in prepared.batch_context_markdown


def test_prepare_batch_context_includes_patchable_section(tmp_path: Path) -> None:
    plan = _plan_with_branches()
    digest = compute_plan_digest(plan)
    output_dir = tmp_path / "planning-output"
    item = plan.item_by_id("item-002")
    assert item is not None
    prepared = prepare_batch_context(
        plan=plan,
        selected_items=[item],
        plan_digest=digest,
        output_dir=output_dir,
        whole_plan_context=WholePlanContextMode.HYBRID,
        max_context_characters=30000,
    )
    assert "Patchable related items" in prepared.batch_context_markdown
    assert "[item-001]" in prepared.batch_context_markdown


def test_plan_overview_artifact_is_reused(tmp_path: Path) -> None:
    plan = _plan_with_branches()
    digest = compute_plan_digest(plan)
    output_dir = tmp_path / "planning-output"
    first = ensure_plan_overview_artifact(output_dir, plan, digest)
    first.write_text("custom", encoding="utf-8")
    second = ensure_plan_overview_artifact(output_dir, plan, digest)
    assert second.read_text(encoding="utf-8") == "custom"


def test_prepare_batch_context_hybrid_mode(tmp_path: Path) -> None:
    plan = _plan_with_branches()
    digest = compute_plan_digest(plan)
    output_dir = tmp_path / "planning-output"
    item = plan.item_by_id("item-002")
    assert item is not None
    prepared = prepare_batch_context(
        plan=plan,
        selected_items=[item],
        plan_digest=digest,
        output_dir=output_dir,
        whole_plan_context=WholePlanContextMode.HYBRID,
        max_context_characters=30000,
    )
    assert prepared.context_mode == WholePlanContextMode.HYBRID
    assert "Assigned generation scope" in prepared.batch_context_markdown
    assert prepared.embedded_overview is not None


def test_prepare_batch_context_referenced_mode(tmp_path: Path) -> None:
    plan = _plan_with_branches()
    digest = compute_plan_digest(plan)
    output_dir = tmp_path / "planning-output"
    item = plan.item_by_id("item-002")
    assert item is not None
    prepared = prepare_batch_context(
        plan=plan,
        selected_items=[item],
        plan_digest=digest,
        output_dir=output_dir,
        whole_plan_context=WholePlanContextMode.REFERENCED,
        max_context_characters=30000,
    )
    assert prepared.context_mode == WholePlanContextMode.REFERENCED
    assert prepared.embedded_overview is None
    assert "plan-overview" in prepared.batch_context_markdown


def test_wave_never_selects_ancestor_and_descendant() -> None:
    plan = _plan_with_branches()
    generation = GenerationConfig(
        batch_strategy=BatchStrategy.THROUGHPUT,
    )
    batches = select_concurrent_batches(plan, generation, max_batches=3)
    selected = [item.id for batch in batches for item in batch]
    if "item-002" in selected:
        assert "item-004" not in selected
    if "item-004" in selected:
        assert "item-002" not in selected


def test_single_strategy_one_item_per_batch() -> None:
    plan = _plan_with_branches()
    generation = GenerationConfig(
        batch_strategy=BatchStrategy.SINGLE,
    )
    batches = select_concurrent_batches(plan, generation, max_batches=3)
    assert all(len(batch) == 1 for batch in batches)


def test_generation_config_precedence(tmp_path: Path) -> None:
    config_path = tmp_path / "planning.yaml"
    config_path.write_text(
        "\n".join(
            [
                "input: ./idea.md",
                "output: ./out",
                "output_goal: Produce a plan",
                "generation:",
                "  batch_size: 2",
                "  batch_strategy: single",
            ]
        ),
        encoding="utf-8",
    )
    options = merge_run_options(config_path=config_path, batch_size=4)
    assert options.generation.batch_size == 4
    assert options.generation.batch_strategy == BatchStrategy.SINGLE


def test_finalize_rejects_stale_plan_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from top_down_planning.persistence import save_plan

    output_dir = tmp_path / "planning-output"
    output_dir.mkdir()
    plan = make_root_plan(
        input_file=str(tmp_path / "idea.md"),
        output_goal="Produce a plan",
        input_digest="a",
        output_goal_digest="b",
    )
    save_plan(output_dir, plan)
    txn_file = output_dir / ".planning-output" / "iterations" / "001-transaction.json"
    txn_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(ENV_TXN_FILE, str(txn_file))
    monkeypatch.setenv(ENV_SELECTED_IDS, "item-001")
    monkeypatch.setenv(ENV_PLAN_FILE, str(output_dir / ".planning-output" / "plan.yaml"))
    monkeypatch.setenv(ENV_PLAN_DIGEST, "expected-digest")
    reset_transaction(txn_file)
    record_operation(
        json_payload=(
            '{"type":"mark_actionable","node_id":"item-001",'
            '"title":"Plan the requested work","objective":"Produce the requested plan.",'
            '"expected_outputs":["Plan"],"acceptance_criteria":["Done"]}'
        )
    )
    draft_path = txn_file.with_suffix(txn_file.suffix + ".draft")
    draft = __import__("json").loads(draft_path.read_text(encoding="utf-8"))
    draft["plan_digest"] = "stale-digest"
    draft_path.write_text(__import__("json").dumps(draft), encoding="utf-8")
    with pytest.raises(PlanToolError, match="plan_digest mismatch"):
        finalize()


def test_validate_wave_rejects_stale_digest() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    response = make_agent_response(
        plan_digest="stale",
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                title="Plan the requested work",
                objective="Produce the requested plan.",
                expected_outputs=["x"],
                acceptance_criteria=["y"],
            )
        ],
    )
    errors = validate_wave_responses(
        plan,
        [(["item-001"], response)],
        limits=PlanningLimits(),
        plan_digest="current-digest",
    )
    assert any("plan_digest mismatch" in error for error in errors)
