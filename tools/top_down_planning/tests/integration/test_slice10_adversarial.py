"""Slice 10 assembled-system adversarial proofs (review-plan scenarios 5–20)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.session_lineage import REASON_PROVIDER_SESSION_NOT_FOUND
from top_down_planning.domain.session_lineage import REASON_PROVIDER_TURN_STALLED
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import primary_provider_session_id
from tests.conftest import run_cli
from tests.helpers import (
    done_events,
    grant_capability,
    only_run_id,
    set_capability_token_file,
    write_agent_request_file,
)
from tests.integration.e2e_helpers import (
    E2EStubProvider,
    planning_single_leaf_script,
    queue_turn,
    script_whole_output_review,
    script_whole_plan_review,
    production_batch_script,
    root_child_item_ids,
    write_e2e_config,
)
from tests.support.run_builders import _create_planning_run
from tests.support.slice10 import (
    assert_audit_events_agree_with_snapshots,
    assert_recovery_lineage_complete,
)


@pytest.fixture
def provider() -> E2EStubProvider:
    return E2EStubProvider()


@pytest.fixture
def patch_provider(provider: E2EStubProvider):
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        yield provider


def _secret_text() -> str:
    return "password=slice10-e2e-secret api_key=sk-slice10-example-key"


def _pause_for_resume(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    expected = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected + 1
    updated["status"] = "paused"
    updated["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": str(run.get("phase") or PLANNING),
        "message": "cancelled for slice 10 resume checks",
        "details": {},
    }
    store.save_run(run_id, updated, expected)


@pytest.mark.integration
def test_resume_accepts_presentation_config_change(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T010001-010001")
    _pause_for_resume(store, run_id)

    result = run_cli(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(store.root),
            "--set",
            "observability.log_level=trace",
            "--check",
            "--stream-json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    payload = result.json()
    assert payload["ok"] is True
    changes = payload.get("config_changes") or payload.get("resume_plan", {}).get("config_changes")
    assert changes
    assert "observability.log_level" in str(changes)


@pytest.mark.integration
def test_resume_rejects_prohibited_contract_drift(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T010002-010002")
    _pause_for_resume(store, run_id)

    result = run_cli(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(store.root),
            "--set",
            "planning.max_depth=2",
            "--check",
            "--stream-json",
        ]
    )
    assert result.exit_code == 1, result.stdout
    payload = result.json()
    assert payload["ok"] is False
    text = json.dumps(payload).lower()
    assert "contract" in text
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    before = store.load_resolved_config(run_id)
    assert int(before["planning"]["max_depth"]) != 2


@pytest.mark.integration
def test_corrupt_persisted_state_fails_closed_through_cli(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T010003-010003")
    run_path = store.run_dir(run_id) / "run.json"
    run_path.write_text("{not-json", encoding="utf-8")

    status = run_cli(["status", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"])
    resume = run_cli(["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"])
    assert status.exit_code != 0
    assert resume.exit_code != 0
    status_payload = status.json()
    resume_payload = resume.json()
    assert status_payload["ok"] is False
    assert resume_payload["ok"] is False
    assert status_payload["error"]["code"] == "corrupt_run"
    assert resume_payload["error"]["code"] == "corrupt_run"


@pytest.mark.integration
def test_stale_plan_revision_is_rejected_through_agent_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_id = run_cli(
        ["run", "--config", str(config_path), "--runs-dir", str(runs_dir), "--stream-json"]
    ).json()["run_id"]
    plan_revision = int(store.load_plan(run_id)["revision"])
    assert plan_revision > 0
    assert store.load_run(run_id)["status"] == "running"
    set_capability_token_file(
        monkeypatch,
        store,
        run_id,
        grant_capability(
            store,
            run_id,
            role="planner",
            phase=str(store.load_run(run_id).get("phase") or PLANNING),
        ),
    )
    request_path = write_agent_request_file(
        store,
        run_id,
        "stale-apply.json",
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"title": "Stale write"},
                }
            ],
        },
    )

    result = run_cli(
        [
            "agent",
            "plan",
            "apply",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--request",
            str(request_path),
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "revision_conflict", payload
    assert int(store.load_plan(run_id)["revision"]) == plan_revision


@pytest.mark.integration
def test_lost_provider_session_is_replaced_with_complete_lineage(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    def mark_missing() -> None:
        run_id = only_run_id(store)
        session_id = primary_provider_session_id(store.load_run(run_id), "planner")
        assert session_id
        patch_provider.mark_session_not_found(session_id)

    patch_provider.script_turn(done_events(signal="continue", text="first planning turn"), mutate_store=mark_missing)
    patch_provider.script_turn(done_events(text="replacement planner start"))
    queue_turn(patch_provider, planning_single_leaf_script(store))
    result = run_cli(
        ["run", "--config", str(config_path), "--runs-dir", str(runs_dir), "--stream-json"]
    )
    assert result.exit_code == 0, result.stderr
    run_id = result.json()["run_id"]
    run = store.load_run(run_id)
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert_recovery_lineage_complete(
        store,
        run_id,
        reason=REASON_PROVIDER_SESSION_NOT_FOUND,
    )
    assert_audit_events_agree_with_snapshots(store, run_id)


@pytest.mark.integration
def test_stalled_provider_exhausts_recovery_without_orphans(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(
        tmp_path / "run.yaml",
        limits={"planning": {"max_agent_turns": 4}},
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)

    def stall_current() -> None:
        run_id = only_run_id(store)
        session_id = primary_provider_session_id(store.load_run(run_id), "planner")
        if session_id:
            patch_provider.mark_session_stalled(session_id)

    patch_provider.script_turn(
        done_events(signal="continue", text="planning before stall"),
        mutate_store=stall_current,
    )
    patch_provider.script_turn(done_events(text="stalled enqueue placeholder"))
    patch_provider.script_turn(
        done_events(text="replacement start"),
        mutate_store=stall_current,
    )
    patch_provider.script_turn(done_events(text="replacement stalled enqueue"))
    result = run_cli(
        ["run", "--config", str(config_path), "--runs-dir", str(runs_dir), "--stream-json"]
    )
    assert result.exit_code != 0
    payload = result.json()
    assert payload["ok"] is False
    run_id = payload["run_id"]
    run = store.load_run(run_id)
    assert run["status"] in {"failed", "paused"}
    stop = run.get("stop") or {}
    assert stop.get("code") in {
        "session_recovery_exhausted",
        "limit_exhausted",
        "provider_turn_failed",
        "provider_unavailable",
    }
    events = store.load_events(run_id)
    assert any(event.get("type") == "session_replacement_started" for event in events)
    started = [event for event in events if event.get("type") == "session_replacement_started"]
    assert started[-1].get("reason") == REASON_PROVIDER_TURN_STALLED
    assert not patch_provider.list_active_sessions()
    assert_audit_events_agree_with_snapshots(store, run_id)


@pytest.mark.integration
def test_audit_events_and_snapshots_agree_after_full_run(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_id = run_cli(
        ["run", "--config", str(config_path), "--runs-dir", str(runs_dir), "--stream-json"]
    ).json()["run_id"]
    script_whole_plan_review(patch_provider, store, run_id, decision="approved")
    run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    leaf_id = root_child_item_ids(store, run_id)[0]
    queue_turn(
        patch_provider,
        production_batch_script(
            store,
            run_id,
            plan_items=[leaf_id],
            dispositions={leaf_id: {"disposition": "completed"}},
            submit_completion=True,
        ),
    )
    run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    script_whole_output_review(patch_provider, store, run_id, decision="approved")
    output = run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    assert output.json()["outcome"] == "accepted"
    assert_audit_events_agree_with_snapshots(store, run_id)


@pytest.mark.integration
def test_provider_secrets_are_redacted_from_console_and_transcript(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    events, mutate = planning_single_leaf_script(store)
    secret_events = []
    for event in events:
        copied = dict(event)
        if copied.get("type") == "done":
            copied["text"] = _secret_text()
        secret_events.append(copied)
    queue_turn(patch_provider, (secret_events, mutate))
    result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
            "--agent-text",
            "--agent-transcript",
            "--log-level",
            "trace",
        ]
    )
    assert result.exit_code == 0, result.stderr
    run_id = result.json()["run_id"]
    combined = result.stdout + result.stderr
    assert "slice10-e2e-secret" not in combined
    assert "sk-slice10-example-key" not in combined
    transcript = store.run_dir(run_id) / "agent-transcript.jsonl"
    if transcript.is_file():
        text = transcript.read_text(encoding="utf-8")
        assert "slice10-e2e-secret" not in text
        assert "sk-slice10-example-key" not in text
    events_text = json.dumps(store.load_events(run_id))
    assert "slice10-e2e-secret" not in events_text
    assert "sk-slice10-example-key" not in events_text


@pytest.mark.integration
def test_repeated_public_commands_are_idempotent_on_terminal_run(
    tmp_path: Path,
    patch_provider: E2EStubProvider,
) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    queue_turn(patch_provider, planning_single_leaf_script(store))
    run_id = run_cli(
        ["run", "--config", str(config_path), "--runs-dir", str(runs_dir), "--stream-json"]
    ).json()["run_id"]
    script_whole_plan_review(patch_provider, store, run_id, decision="approved")
    run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    leaf_id = root_child_item_ids(store, run_id)[0]
    queue_turn(
        patch_provider,
        production_batch_script(
            store,
            run_id,
            plan_items=[leaf_id],
            dispositions={leaf_id: {"disposition": "completed"}},
            submit_completion=True,
        ),
    )
    run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    script_whole_output_review(patch_provider, store, run_id, decision="approved")
    first = run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    assert first.json()["outcome"] == "accepted"
    before = store.load_run(run_id)
    before_events = store.load_events(run_id)
    before_prod = store.load_production(run_id)
    turns_before = patch_provider.turn_count() if hasattr(patch_provider, "turn_count") else None

    second = run_cli(["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    status_a = run_cli(["status", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    status_b = run_cli(["status", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    inspect_a = run_cli(["inspect", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])
    inspect_b = run_cli(["inspect", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json"])

    after = store.load_run(run_id)
    after_events = store.load_events(run_id)
    after_prod = store.load_production(run_id)
    assert second.json()["outcome"] == "accepted"
    assert after["revision"] == before["revision"]
    assert after["status"] == before["status"]
    assert len(after_events) == len(before_events)
    assert after_prod["revision"] == before_prod["revision"]
    assert status_a.exit_code == 0
    assert status_a.json() == status_b.json()
    assert inspect_a.exit_code == 0
    assert inspect_a.json() == inspect_b.json()
    if turns_before is not None:
        assert patch_provider.turn_count() == turns_before
