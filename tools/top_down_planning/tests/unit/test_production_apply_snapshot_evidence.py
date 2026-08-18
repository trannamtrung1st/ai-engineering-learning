"""Tests for apply-time production snapshot evidence validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import atomic_write_json
from top_down_planning.agent_tool import (
    ProductionAgentService,
    ProductionContextMutationError,
    ProductionEvidenceIncompleteError,
    RequestError,
)
from top_down_planning.config import resolve_config
from top_down_planning.config.context_digests import (
    is_evidence_authorizable_binding_key,
    split_unauthorized_snapshot_paths,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    create_run_kwargs,
    grant_capability,
    save_review_payload,
    whole_plan_approval_record,
    write_config,
)
from tests.unit.test_agent_production_tool import _batch_apply_request, _create_production_run


def test_binding_key_classification_defaults_unknown_to_non_authorizable() -> None:
    binding = {
        "resource_digests": {"src/feature.py": "a" * 64},
        "skill_digests": {},
        "guidance_digests": [],
    }
    assert not is_evidence_authorizable_binding_key(
        "src/unknown.py",
        binding=binding,
    )


def test_binding_key_classification_uses_digest_maps() -> None:
    binding = {
        "resource_digests": {
            "src/feature.py": "a" * 64,
            "src/helper.py": "d" * 64,
        },
        "skill_digests": {"skills/demo/SKILL.md": "b" * 64},
        "guidance_digests": [{"path": "docs/guide.md", "digest": "c" * 64}],
    }
    assert is_evidence_authorizable_binding_key(
        "src/feature.py",
        binding=binding,
    )
    assert not is_evidence_authorizable_binding_key(
        "skills/demo/SKILL.md",
        binding=binding,
    )
    assert not is_evidence_authorizable_binding_key(
        "docs/guide.md",
        binding=binding,
    )
    evidence_gaps, context_mutations = split_unauthorized_snapshot_paths(
        ("src/helper.py", "skills/demo/SKILL.md"),
        binding=binding,
    )
    assert evidence_gaps == ("src/helper.py",)
    assert context_mutations == ("skills/demo/SKILL.md",)


def _production_run_with_src_binding(
    tmp_path: Path,
    *,
    run_id: str = "run-20260101T000701-000701",
) -> tuple[FileRunStore, str]:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    (src / "feature.py").write_text("v1\n", encoding="utf-8")
    (workspace / "README.md").write_text("# Goal\n", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Deliver the feature.
  input_refs:
    - README.md
agent_context:
  roles:
    producer:
      resources:
        - src/
limits:
  production:
    max_batches: 50
    max_agent_turns_per_batch: 10
provider:
  name: stub
""",
        ),
        cwd=workspace,
    )

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-first": first, "item-second": second},
    )
    store = FileRunStore(tmp_path / "runs")
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    return store, run_id


def test_apply_succeeds_when_outputs_cover_changed_snapshot_path(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    feature.write_text("v2\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    result = service.apply(
        {
            **_batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            "outputs": [
                {
                    "id": "out-feature",
                    "type": "artifact",
                    "ref": "src/feature.py",
                }
            ],
        },
        capability_token=token,
    )

    assert result["ok"] is True
    assert result["production_revision"] == 1


def test_apply_fails_when_changed_snapshot_path_missing_from_outputs(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    helper = workspace / "src" / "helper.py"
    feature.write_text("v2\n", encoding="utf-8")
    helper.write_text("new\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(ProductionEvidenceIncompleteError, match="snapshot-bound paths") as exc_info:
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [
                    {
                        "id": "out-feature",
                        "type": "artifact",
                        "ref": "src/feature.py",
                    }
                ],
            },
            capability_token=token,
        )

    assert "src/helper.py" in str(exc_info.value)
    assert exc_info.value.code == "production_evidence_incomplete"
    assert "src/helper.py" in exc_info.value.unauthorized_paths
    assert exc_info.value.production_revision == 0
    assert exc_info.value.retryable is True
    assert "production_revision=0" in str(exc_info.value)
    production = store.load_production(run_id)
    assert production["revision"] == 0
    assert production["batches"] == []


def test_retry_with_complete_outputs_succeeds(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    helper = workspace / "src" / "helper.py"
    feature.write_text("v2\n", encoding="utf-8")
    helper.write_text("new\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    request = {
        **_batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        "outputs": [
            {"id": "out-feature", "type": "artifact", "ref": "src/feature.py"},
            {"id": "out-helper", "type": "artifact", "ref": "src/helper.py"},
        ],
    }

    with pytest.raises(ProductionEvidenceIncompleteError):
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
            },
            capability_token=token,
        )

    result = service.apply(request, capability_token=token)
    assert result["ok"] is True
    assert result["production_revision"] == 1


def test_prior_batch_evidence_authorizes_cumulative_drift(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    feature.write_text("v2\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service.apply(
        {
            **_batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
        },
        capability_token=token,
    )

    helper = workspace / "src" / "helper.py"
    helper.write_text("new\n", encoding="utf-8")

    with pytest.raises(ProductionEvidenceIncompleteError, match="src/helper.py"):
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-second"],
                    dispositions={"item-second": {"disposition": "completed"}},
                    production_revision=1,
                ),
                "outputs": [{"id": "out-feature-v2", "type": "artifact", "ref": "src/feature.py"}],
            },
            capability_token=token,
        )


def test_paths_outside_snapshot_binding_do_not_trigger_apply_error(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_production_run(store)
    run_id = "run-20260101T000201-000201"
    workspace = Path(store.load_run(run_id)["workspace"])
    outside = workspace / "outside.py"
    outside.write_text("orphan\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    result = service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        capability_token=token,
    )

    assert result["ok"] is True


def test_no_drift_apply_succeeds_without_snapshot_error(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    result = service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        capability_token=token,
    )

    assert result["ok"] is True


def _artifact_snapshot_count(store: FileRunStore, run_id: str) -> int:
    artifacts_dir = store.artifacts_dir(run_id)
    if not artifacts_dir.is_dir():
        return 0
    return sum(1 for path in artifacts_dir.rglob("*") if path.is_file())


def test_failed_apply_does_not_leave_orphan_artifact_snapshots(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    helper = workspace / "src" / "helper.py"
    feature.write_text("v2\n", encoding="utf-8")
    helper.write_text("new\n", encoding="utf-8")

    before = _artifact_snapshot_count(store, run_id)
    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(ProductionEvidenceIncompleteError):
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
            },
            capability_token=token,
        )

    assert _artifact_snapshot_count(store, run_id) == before
    production = store.load_production(run_id)
    assert production["revision"] == 0
    assert production["batches"] == []


def test_invalidated_batch_evidence_does_not_authorize_apply_drift(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    feature.write_text("v2\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service.apply(
        {
            **_batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
        },
        capability_token=token,
    )
    service.apply(
        {
            **_batch_apply_request(
                plan_items=["item-second"],
                dispositions={"item-second": {"disposition": "completed"}},
                production_revision=1,
            ),
            "outputs": [],
            "empty_output": True,
            "empty_output_reason": "no files touched",
        },
        capability_token=token,
    )

    production = dict(store.load_production(run_id))
    expected_revision = int(production["revision"])
    production["revision"] = expected_revision + 1
    production["batches"] = [
        {
            **dict(production["batches"][0]),
            "evidence_status": "invalidated_by_reconciliation",
            "invalidated_item_ids": ["item-first"],
        },
        dict(production["batches"][1]),
    ]
    production["output_evidence"] = [
        entry
        for entry in production["output_evidence"]
        if str(entry.get("batch_id") or "") != str(production["batches"][0]["id"])
    ]
    production["dispositions"] = {"item-second": "completed"}
    store.save_production(run_id, production, expected_revision=expected_revision)

    feature.write_text("v3\n", encoding="utf-8")

    with pytest.raises(ProductionEvidenceIncompleteError, match="src/feature.py"):
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                    production_revision=3,
                ),
                "outputs": [],
                "empty_output": True,
                "empty_output_reason": "no files touched",
            },
            capability_token=token,
        )


def test_invalid_evidence_refs_fail_at_apply_time(tmp_path: Path) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    (workspace / "src" / "feature.py").write_text("v2\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="workspace-relative|invalid evidence refs"):
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [
                    {
                        "id": "out-bad",
                        "type": "artifact",
                        "ref": "/etc/passwd",
                    }
                ],
            },
            capability_token=token,
        )


def test_guidance_drift_raises_context_mutation_error(tmp_path: Path) -> None:
    from core_tools.persistence import dump_yaml

    store, run_id = _production_run_with_src_binding(tmp_path)
    config = dict(store.load_resolved_config(run_id))
    agent_context = dict(config.get("agent_context") or {})
    roles = dict(agent_context.get("roles") or {})
    producer = dict(roles.get("producer") or {})
    producer["guidance"] = [{"text": "Revised inline guidance for apply drift."}]
    roles["producer"] = producer
    agent_context["roles"] = roles
    config["agent_context"] = agent_context
    config_path = store.run_dir(run_id) / "resolved-config.yaml"
    config_path.write_text(dump_yaml(config) + "\n", encoding="utf-8")
    from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_config_update

    run = store.load_run(run_id)
    workspace = Path(str(run.get("workspace") or store.root)).resolve()
    run = bind_run_digests_for_config_update(run, config, workspace=workspace)
    atomic_write_json(store.run_dir(run_id) / "run.json", run)

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(ProductionContextMutationError, match="inline guidance") as exc_info:
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            capability_token=token,
        )

    assert exc_info.value.code == "production_context_mutation_unauthorized"
    assert exc_info.value.retryable is False


def test_evidence_incomplete_error_includes_drift_count_reconciliation(
    tmp_path: Path,
) -> None:
    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    (workspace / "src" / "feature.py").write_text("v2\n", encoding="utf-8")
    (workspace / "src" / "helper.py").write_text("new\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(ProductionEvidenceIncompleteError) as exc_info:
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
            },
            capability_token=token,
        )

    payload = exc_info.value.to_dict()
    assert payload["changed_snapshot_paths"] == payload["authorized_changed_paths"] + len(
        payload["unauthorized_changed_paths"]
    )


def test_completion_gate_still_blocks_unauthorized_drift_after_valid_apply(
    tmp_path: Path,
) -> None:
    from core_tools.provider import StubProvider
    from top_down_planning.orchestrator import ProductionPhaseOrchestrator
    from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
    from tests.helpers import done_events

    store, run_id = _production_run_with_src_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    feature = workspace / "src" / "feature.py"
    feature.write_text("v2\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service.apply(
        {
            **_batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
            ),
            "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
        },
        capability_token=token,
    )
    service.apply(
        {
            **_batch_apply_request(
                plan_items=["item-second"],
                dispositions={"item-second": {"disposition": "completed"}},
                production_revision=1,
            ),
            "outputs": [{"id": "out-feature-v2", "type": "artifact", "ref": "src/feature.py"}],
            "empty_output": False,
        },
        capability_token=token,
    )

    helper = workspace / "src" / "helper.py"
    helper.write_text("orphan drift\n", encoding="utf-8")

    service.submit_completion(
        {"goal_assessment": "Done.", "production_revision": int(store.load_production(run_id)["revision"])},
        capability_token=token,
    )

    provider = StubProvider()
    provider.script_turn(done_events(text="resume"))
    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert store.load_run(run_id)["phase"] == PRODUCTION
    assert store.load_run(run_id)["phase"] != WHOLE_OUTPUT_REVIEW


def _production_run_with_skill_binding(
    tmp_path: Path,
    *,
    run_id: str = "run-20260101T000702-000702",
) -> tuple[FileRunStore, str]:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    (src / "feature.py").write_text("v1\n", encoding="utf-8")
    skill_dir = workspace / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# demo\n\nbody\n", encoding="utf-8")
    (workspace / "README.md").write_text("# Goal\n", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Deliver the feature.
  input_refs:
    - README.md
agent_context:
  roles:
    producer:
      resources:
        - src/
      skills:
        - skills/demo
limits:
  production:
    max_batches: 50
    max_agent_turns_per_batch: 10
provider:
  name: stub
""",
        ),
        cwd=workspace,
    )

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-first": first},
    )
    store = FileRunStore(tmp_path / "runs")
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    return store, run_id


def test_skill_drift_raises_context_mutation_not_evidence_incomplete(
    tmp_path: Path,
) -> None:
    store, run_id = _production_run_with_skill_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    skill_file = workspace / "skills" / "demo" / "SKILL.md"
    feature = workspace / "src" / "feature.py"
    skill_file.write_text("# demo\n\nupdated body\n", encoding="utf-8")
    feature.write_text("v2\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(ProductionContextMutationError, match="skills/demo/SKILL.md") as exc_info:
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
            },
            capability_token=token,
        )

    assert exc_info.value.code == "production_context_mutation_unauthorized"
    assert "skills/demo/SKILL.md" in exc_info.value.context_mutation_paths
    assert "src/feature.py" not in exc_info.value.context_mutation_paths


def test_mixed_snapshot_failure_reports_both_partitions_and_reconciles_counts(
    tmp_path: Path,
) -> None:
    store, run_id = _production_run_with_skill_binding(tmp_path)
    workspace = Path(store.load_run(run_id)["workspace"])
    skill_file = workspace / "skills" / "demo" / "SKILL.md"
    feature = workspace / "src" / "feature.py"
    helper = workspace / "src" / "helper.py"
    skill_file.write_text("# demo\n\nupdated body\n", encoding="utf-8")
    feature.write_text("v2\n", encoding="utf-8")
    helper.write_text("new\n", encoding="utf-8")

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(ProductionContextMutationError) as exc_info:
        service.apply(
            {
                **_batch_apply_request(
                    plan_items=["item-first"],
                    dispositions={"item-first": {"disposition": "completed"}},
                ),
                "outputs": [{"id": "out-feature", "type": "artifact", "ref": "src/feature.py"}],
            },
            capability_token=token,
        )

    payload = exc_info.value.to_dict()
    assert "skills/demo/SKILL.md" in payload["context_mutation_paths"]
    assert "src/helper.py" in payload["evidence_gap_paths"]
    assert payload["changed_snapshot_paths"] == payload["authorized_changed_paths"] + len(
        payload["unauthorized_changed_paths"]
    )
