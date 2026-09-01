"""CLI tests for ``tdp resume --check`` and structured diagnostics (§21 test 22)."""

from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.resume_diagnostics import format_resume_plan_summary_text
from top_down_planning.cli.user import handle_resume_command
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.session_policy import register_session_policy_executor
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config, whole_plan_approval_record
from tests.support.run_builders import _create_paused_production_run, _sample_plan


def _run_dir_digest(run_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(run_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_resume_check_performs_no_writes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    run_dir = store.run_dir(run_id)
    before = _run_dir_digest(run_dir)

    with patch("top_down_planning.cli.user.emit_message"):
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=True,
                set=["limits.production.max_batches=99"],
                config=None,
                command="resume",
            )
        )

    assert _run_dir_digest(run_dir) == before


def test_resume_check_includes_limit_budget_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)

    with pytest.raises(SystemExit) as exit_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=True,
                set=["limits.production.max_batches=99"],
                config=None,
                command="resume",
            )
        )
    assert exit_info.value.code == 0

    output = capsys.readouterr().out
    assert "Run is resumable." in output
    assert "limits.production.max_batches" in output
    assert "consumed=1" in output
    assert "remaining=98" in output


def test_resume_check_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)

    with pytest.raises(SystemExit) as exit_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=True,
                check=True,
                set=["limits.production.max_batches=99"],
                config=None,
                command="resume",
            )
        )
    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["check_only"] is True
    assert payload["limit_diagnostics"]
    assert payload["config_changes"]["limits.production.max_batches"]["to"] == 99


def test_resume_check_reports_lifecycle_diagnostics_without_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from top_down_planning.domain.production_blockers import (
        BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
        BLOCKER_STATUS_ACTIVE,
    )
    from tests.helpers import make_review_loop, save_review_payload

    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=0,
        scope={"kind": "focused_output", "item_ids": ["item-root"]},
        status="approved",
        reviewer_session_id="sess",
        verification_result={"target_digest": "digest-a", "decision": "verified"},
    )
    save_review_payload(store, run_id, loop.to_dict())
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
        "status": BLOCKER_STATUS_ACTIVE,
        "review_loop_id": loop.id,
        "target_revision": 0,
        "target_digest": "digest-a",
        "evidence": "Waiting on focused review.",
        "affected_refs": ["item-root"],
        "summary": "focused review pending",
    }
    store.save_production(run_id, updated, expected)
    run_dir = store.run_dir(run_id)
    before = _run_dir_digest(run_dir)

    with pytest.raises(SystemExit) as exit_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=True,
                check=True,
                set=None,
                config=None,
                command="resume",
            )
        )
    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    codes = [row["code"] for row in payload.get("lifecycle_diagnostics") or []]
    assert "stale_review_bound_blocker" in codes
    row = next(
        item
        for item in payload["lifecycle_diagnostics"]
        if item["code"] == "stale_review_bound_blocker"
    )
    assert row["loop_id"] == loop.id
    assert row["proposed_reconciliation"]
    assert _run_dir_digest(run_dir) == before


def test_resume_check_rejects_unsupported_plan_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    plan_path = store.run_dir(run_id) / "plan.json"
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_payload["schema_version"] = 1
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=True,
                check=True,
                set=[],
                config=None,
                command="resume",
            )
        )

    assert exit_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_plan_schema"
    assert "Recreate the run" in payload["error"]["message"]


def test_resume_check_allows_limit_decrease_without_consumed_tracking(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "cancelled",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)

    with pytest.raises(SystemExit) as exit_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=True,
                set=["limits.production.max_batches=1"],
                config=None,
                command="resume",
            )
        )
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "Run is resumable." in output
    assert "limits.production.max_batches" in output
    assert "candidate=1" in output


def test_resume_apply_prints_same_summary_as_check(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    args = Namespace(
        run=run_id,
        runs_dir=str(store.root),
        stream_json=False,
        check=False,
        set=["limits.production.max_batches=99"],
        config=None,
        command="resume",
    )

    check_text = StringIO()
    with patch("top_down_planning.cli.user.emit_message", side_effect=lambda msg, **_: check_text.write(msg)):
        handle_resume_command(
            Namespace(**{**vars(args), "check": True}),
        )
    check_output = check_text.getvalue()

    apply_output = StringIO()
    with patch("sys.stdout", apply_output):
        with patch("top_down_planning.cli.user._build_run_engine") as build_engine:
            engine = build_engine.return_value
            engine.continue_run.return_value.ok = False
            engine.continue_run.return_value.phase = PRODUCTION
            engine.continue_run.return_value.status = "paused"
            engine.continue_run.return_value.outcome = None
            engine.continue_run.return_value.steps = []
            engine.continue_run.return_value.reason = "test stop"
            engine.continue_run.return_value.cancelled = False
            with patch("top_down_planning.cli.user.emit_message", side_effect=lambda msg, **_: apply_output.write(msg)):
                handle_resume_command(args)

    assert apply_output.getvalue().startswith(check_output)


def test_resume_check_rejects_failed_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002301-002301"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "failed"
    run["stop"] = {
        "code": "orchestrator_invariant_failure",
        "category": "invariant",
        "phase": PLANNING,
        "message": "failed",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)

    with patch("top_down_planning.cli.user.emit_error_message") as emit_error:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=True,
                set=[],
                config=None,
                command="resume",
            )
        )
        assert emit_error.call_args.kwargs["code"] == "failed_run_not_resumable"


def test_session_policy_executor_hook(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    seen: list[dict] = []

    def _executor(_store, _run_id, session_policy: dict) -> None:
        seen.append(dict(session_policy))

    register_session_policy_executor(_executor)
    try:
        from top_down_planning.orchestrator.session_policy import (
            execute_session_policy_if_registered,
        )

        execute_session_policy_if_registered(store, run_id, {"status": "test"})
        assert seen == [{"status": "test"}]

        with patch("top_down_planning.cli.user.emit_message"):
            with patch("top_down_planning.cli.user._build_run_engine") as build_engine:
                engine = build_engine.return_value
                engine.continue_run.return_value.ok = True
                engine.continue_run.return_value.phase = PRODUCTION
                engine.continue_run.return_value.status = "running"
                engine.continue_run.return_value.outcome = None
                engine.continue_run.return_value.steps = []
                engine.continue_run.return_value.reason = None
                engine.continue_run.return_value.cancelled = False
                handle_resume_command(
                    Namespace(
                        run=run_id,
                        runs_dir=str(store.root),
                        stream_json=False,
                        check=False,
                        set=["limits.production.max_batches=99"],
                        config=None,
                        command="resume",
                    )
                )
                assert engine.continue_run.call_args.kwargs["session_policy"]
    finally:
        register_session_policy_executor(None)


def test_format_resume_plan_summary_text_includes_config_overrides() -> None:
    text = format_resume_plan_summary_text(
        {
            "already_completed": False,
            "comparison_ok": True,
            "stop_summary": "limit_exhausted: limits.production.max_batches exhausted at 1/1",
            "config_changes": {
                "limits.production.max_batches": {"from": 1, "to": 99},
            },
            "limit_diagnostics": [
                {
                    "path": "limits.production.max_batches",
                    "consumed": 1,
                    "stored_limit": 1,
                    "candidate_limit": 99,
                    "remaining_budget": 98,
                }
            ],
            "state_transition": {
                "from": "paused",
                "to": "running",
                "prior_stop_code": "limit_exhausted",
            },
            "session_policy_text": (
                "resume planner session cursor-abc123\n"
                "replace once if Cursor reports session not found"
            ),
            "config_path": "/tmp/updated.yaml",
            "config_overrides": ["limits.production.max_batches=99"],
        }
    )
    assert "Run is resumable." in text
    assert "limits.production.max_batches" in text
    assert "updated.yaml" in text


def test_format_resume_plan_summary_text_includes_context_spec_drift_note() -> None:
    text = format_resume_plan_summary_text(
        {
            "already_completed": False,
            "comparison_ok": True,
            "context_spec_may_change": True,
            "session_policy_text": "resume planner session cursor-abc123",
        }
    )
    assert "model-only drift accepted" in text
    assert "digests.context_spec will rebind on apply" in text


def test_resume_check_with_allow_config_drift_shows_ignored_changes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)

    with pytest.raises(SystemExit) as exc_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=True,
                set=["run.output_goal=Tweaked goal."],
                config=None,
                command="resume",
                allow_config_drift=True,
            )
        )
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "Ignored changes" in output
    assert "run.output_goal" in output
    assert "will not take effect" in output


def test_resume_completed_blocked_reports_not_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002301-002301"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PRODUCTION,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "completed"
    run["outcome"] = "blocked"
    run["stop"] = None
    store.save_run(run_id, run, expected_revision)

    with pytest.raises(SystemExit) as exc_info:
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=False,
                set=[],
                config=None,
                command="resume",
                allow_config_drift=False,
            )
        )
    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "already terminated" in output
