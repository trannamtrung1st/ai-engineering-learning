"""§12 production-completion regression: caches must not false-fail rebase."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_production,
    create_run_kwargs,
    done_events,
    minimal_resolved_config,
    whole_plan_approval_record,
)


def _batch_request(
    *,
    plan_items: list[str],
    dispositions: dict,
    production_revision: int = 0,
    outputs: list[dict] | None = None,
) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": outputs or [],
        "contributions": [],
        "summary": "batch complete",
        "empty_output": not bool(outputs),
        "empty_output_reason": None if outputs else "n/a",
    }


def _cache_noise(src: Path) -> None:
    cache = src / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "feature.cpython-314.pyc").write_bytes(b"\0pyc")
    (src / "sidecar.pyc").write_bytes(b"\0pyc2")
    pytest_cache = src / ".pytest_cache" / "v"
    pytest_cache.mkdir(parents=True, exist_ok=True)
    (pytest_cache / "cache").write_text("noise\n", encoding="utf-8")


def _assert_no_cache_paths(paths: list[str] | set[str] | dict[str, str]) -> None:
    keys = list(paths) if not isinstance(paths, dict) else list(paths)
    assert not any(
        "__pycache__" in path or path.endswith(".pyc") or ".pytest_cache" in path
        for path in keys
    )


def _create_dir_resource_run(
    store: FileRunStore,
    *,
    run_id: str,
    workspace: Path,
) -> tuple[Path, Path]:
    src = workspace / "src"
    tests_dir = workspace / "tests"
    src.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (src / "feature.py").write_text("v1\n", encoding="utf-8")
    (src / "helper.py").write_text("helper-v1\n", encoding="utf-8")
    (tests_dir / "test_feature.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (workspace / "task.md").write_text("task\n", encoding="utf-8")

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-leaf": leaf},
    )
    config = minimal_resolved_config(
        run={
            "output_goal": "Deliver the feature.",
            "input_refs": ["task.md"],
        },
        limits={"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        agent_context={
            "default": {"resources": [], "skills": []},
            "planner": {"resources": [], "skills": []},
            "producer": {"resources": ["src/", "tests/"], "skills": []},
            "reviewer": {"resources": ["src/", "tests/"], "skills": []},
        },
        # Defaults enabled via DEFAULT_CONFIG.context_snapshot.excludes.defaults
    )
    assert config["context_snapshot"]["excludes"]["defaults"] is True
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=config),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    return src / "feature.py", src / "helper.py"


def test_production_completion_succeeds_despite_cache_noise(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T012001-012001"
    feature, _helper = _create_dir_resource_run(store, run_id=run_id, workspace=tmp_path)

    initial = store.load_run(run_id)["context_snapshot_binding"]
    _assert_no_cache_paths(initial["resource_digests"])
    assert "src/feature.py" in initial["resource_digests"]
    assert "src/helper.py" in initial["resource_digests"]

    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            feature.write_text("v2-produced\n", encoding="utf-8"),
            _cache_noise(feature.parent),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-leaf"],
                    dispositions={"item-leaf": {"disposition": "completed"}},
                    outputs=[
                        {
                            "id": "output-feature",
                            "type": "artifact",
                            "ref": "src/feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met."},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    rebased = store.load_run(run_id)["context_snapshot_binding"]
    _assert_no_cache_paths(rebased["resource_digests"])
    assert rebased["resource_digests"]["src/feature.py"] != initial["resource_digests"]["src/feature.py"]
    assert rebased["resource_digests"]["src/helper.py"] == initial["resource_digests"]["src/helper.py"]

    events = store.load_events(run_id)
    rebased_events = [e for e in events if e.get("type") == "context_snapshot_rebased"]
    assert len(rebased_events) == 1
    changed = rebased_events[0].get("changed_paths") or []
    assert "src/feature.py" in changed
    _assert_no_cache_paths(changed)
    collected = [e for e in events if e.get("type") == "context_snapshot_collected"]
    assert collected
    assert collected[-1].get("policy_version") == "snapshot-excludes-v1"


def test_production_completion_fails_on_unauthorized_source_not_caches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T012002-012002"
    feature, helper = _create_dir_resource_run(store, run_id=run_id, workspace=tmp_path)

    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            feature.write_text("v2-produced\n", encoding="utf-8"),
            _cache_noise(feature.parent),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-leaf"],
                    dispositions={"item-leaf": {"disposition": "completed"}},
                    outputs=[
                        {
                            "id": "output-feature",
                            "type": "artifact",
                            "ref": "src/feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
            helper.write_text("helper-unauthorized\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met."},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    reason = result.reason or ""
    assert "- src/helper.py" in reason
    assert "__pycache__" not in reason
    assert ".pytest_cache" not in reason
    assert ".pyc" not in reason
    # Authorized feature edit must not be reported as unauthorized.
    unauthorized_section = reason.split("unauthorized snapshot-bound changes detected:")[-1]
    assert "src/feature.py" not in unauthorized_section


def test_production_completion_fails_on_unauthorized_deletion(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T012003-012003"
    feature, helper = _create_dir_resource_run(store, run_id=run_id, workspace=tmp_path)

    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            feature.write_text("v2-produced\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-leaf"],
                    dispositions={"item-leaf": {"disposition": "completed"}},
                    outputs=[
                        {
                            "id": "output-feature",
                            "type": "artifact",
                            "ref": "src/feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
            helper.unlink(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met."},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert "- src/helper.py" in (result.reason or "")


def test_production_completion_fails_on_unauthorized_addition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T012004-012004"
    feature, _helper = _create_dir_resource_run(store, run_id=run_id, workspace=tmp_path)

    provider = StubProvider()
    provider.script_turn(done_events(text="producer session start"))
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            feature.write_text("v2-produced\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                _batch_request(
                    plan_items=["item-leaf"],
                    dispositions={"item-leaf": {"disposition": "completed"}},
                    outputs=[
                        {
                            "id": "output-feature",
                            "type": "artifact",
                            "ref": "src/feature.py",
                        }
                    ],
                ),
                handler="apply",
            )(),
            (feature.parent / "extra.py").write_text("new\n", encoding="utf-8"),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met."},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert "- src/extra.py" in (result.reason or "")
