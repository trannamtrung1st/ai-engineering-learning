"""Unit tests for desktop notifications."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.main import build_parser
from top_down_planning.config import resolve_config
from top_down_planning.invocation import (
    invocation_options_from_args,
    invocation_to_dict,
    merge_invocation_metadata,
    notification_options_from_args_and_config,
    sync_invocation_notifications_from_config,
)
from top_down_planning.notifications.bridge import (
    NotificationDedupeState,
    handle_audit_event,
    short_run_id,
)
from top_down_planning.notifications.desktop import _notifications_suppressed
from top_down_planning.notifications.options import NotificationOptions
from top_down_planning.notifications.outcome import notify_run_outcome
from top_down_planning.notifications.store import (
    NotificationContext,
    NotifyingRunStore,
    wrap_run_store,
)
from top_down_planning.observability import ObservabilityContext, ObservingRunStore
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_config_contract_digest
from core_tools.provider import StubProvider
from tests.conftest import run_cli
from tests.helpers import (
    apply_plan,
    create_run_kwargs,
    done_events,
    minimal_resolved_config,
    only_run_id,
    with_root_contract,
    write_config,
)


def _parse(argv: list[str]) -> Namespace:
    return build_parser().parse_args(argv)


def test_notification_defaults_enabled() -> None:
    args = _parse(["run", "--config", "cfg.yaml"])
    options = notification_options_from_args_and_config(args)
    assert options == NotificationOptions()


def test_yaml_notifications_apply_when_cli_omits_flag(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "notify.yaml",
        """
run:
  output_goal: Goal.
notifications:
  progress: true
  terminal: false
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path)])
    options = notification_options_from_args_and_config(args, resolved_config=resolved)
    assert options.progress is True
    assert options.terminal is False
    assert options.enabled is True


def test_no_notify_overrides_yaml_enabled_true(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "notify.yaml",
        """
run:
  output_goal: Goal.
notifications:
  enabled: true
""",
    )
    resolved = resolve_config(config_path)
    args = _parse(["run", "--config", str(config_path), "--no-notify"])
    options = notification_options_from_args_and_config(args, resolved_config=resolved)
    assert options.enabled is False


def test_set_override_applies_notifications_progress(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "notify.yaml",
        "run:\n  output_goal: Goal.\n",
    )
    resolved = resolve_config(config_path, ["notifications.progress=true"])
    args = _parse(
        [
            "run",
            "--config",
            str(config_path),
            "--set",
            "notifications.progress=true",
        ]
    )
    options = notification_options_from_args_and_config(args, resolved_config=resolved)
    assert options.progress is True


def test_notifications_changes_do_not_affect_config_digest(tmp_path: Path) -> None:
    base_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
planning:
  max_depth: 4
""",
    )
    notify_path = write_config(
        tmp_path / "notify.yaml",
        """
run:
  output_goal: Goal.
planning:
  max_depth: 4
notifications:
  enabled: false
  progress: true
""",
    )
    base = resolve_config(base_path)
    notify = resolve_config(notify_path)
    assert compute_config_contract_digest(base) == compute_config_contract_digest(notify)


def test_invocation_to_dict_includes_notifications() -> None:
    args = _parse(["run", "--config", "cfg.yaml", "--no-notify"])
    invocation = invocation_options_from_args(args)
    payload = invocation_to_dict(invocation)
    assert payload["notifications"] == {
        "enabled": False,
        "terminal": True,
        "phase": True,
        "progress": False,
    }


def test_merge_and_sync_invocation_notifications() -> None:
    stored = {"notifications": {"enabled": True, "progress": False}}
    candidate = {"notifications": {"progress": True}}
    merged = merge_invocation_metadata(stored, candidate)
    assert merged["notifications"]["enabled"] is True
    assert merged["notifications"]["progress"] is True

    synced = sync_invocation_notifications_from_config(
        merged,
        {"notifications": {"terminal": False, "phase": False}},
    )
    assert synced["notifications"]["terminal"] is False
    assert synced["notifications"]["phase"] is False
    assert synced["notifications"]["progress"] is True


def test_notifications_suppressed_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert _notifications_suppressed() is True


def test_notifications_suppressed_on_headless_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("headless Linux suppression is platform-specific")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert _notifications_suppressed() is True


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_user_cancelled_pause_uses_cancelled_title(send_mock) -> None:
    options = NotificationOptions()
    sent = handle_audit_event(
        {
            "type": "run_paused",
            "stop": {
                "code": "user_cancelled",
                "message": "cancelled by user",
            },
        },
        run_id="run-1",
        options=options,
        phase="planning",
    )
    assert sent is True
    title, message = send_mock.call_args.args
    assert title == "TDP run cancelled"
    assert "cancelled by user" in message


def test_short_run_id_uses_suffix() -> None:
    assert short_run_id("run-20260101T002201-002201") == "002201"


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_terminal_tier(send_mock) -> None:
    options = NotificationOptions()
    sent = handle_audit_event(
        {"type": "outcome_resolved", "outcome": "success"},
        run_id="run-20260101T002201-002201",
        options=options,
        phase="output_validated",
    )
    assert sent is True
    send_mock.assert_called_once()
    title, message = send_mock.call_args.args
    assert title == "TDP run complete"
    assert "002201" in message
    assert "output validated" in message
    assert "run-20260101T002201-002201" not in message


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_respects_disabled_tier(send_mock) -> None:
    options = NotificationOptions(progress=False)
    assert (
        handle_audit_event(
            {"type": "production_batch_recorded", "batch_id": "b1"},
            run_id="run-1",
            options=options,
            phase="production",
        )
        is False
    )
    send_mock.assert_not_called()


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_dedupes_pause_and_limit(send_mock) -> None:
    options = NotificationOptions()
    state = NotificationDedupeState()
    handle_audit_event(
        {"type": "run_paused", "reason": "limit"},
        run_id="run-1",
        options=options,
        phase="planning",
        dedupe_state=state,
    )
    handle_audit_event(
        {"type": "planning_limit_exceeded"},
        run_id="run-1",
        options=options,
        phase="planning",
        dedupe_state=state,
    )
    assert send_mock.call_count == 1


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_dedupes_output_approval_and_outcome(send_mock) -> None:
    options = NotificationOptions()
    state = NotificationDedupeState()
    completed_run = {"status": "completed", "phase": "output_validated"}
    handle_audit_event(
        {"type": "whole_output_review_approved"},
        run_id="run-1",
        options=options,
        phase="whole_output_review",
        run=completed_run,
        dedupe_state=state,
    )
    handle_audit_event(
        {"type": "outcome_resolved", "outcome": "success"},
        run_id="run-1",
        options=options,
        phase="output_validated",
        run=completed_run,
        dedupe_state=state,
    )
    assert send_mock.call_count == 1
    assert send_mock.call_args.args[0] == "TDP run complete"


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_sends_output_approval_when_terminal_disabled(send_mock) -> None:
    options = NotificationOptions(terminal=False, phase=True)
    completed_run = {"status": "completed", "phase": "output_validated"}
    approval_sent = handle_audit_event(
        {"type": "whole_output_review_approved"},
        run_id="run-1",
        options=options,
        phase="whole_output_review",
        run=completed_run,
    )
    outcome_sent = handle_audit_event(
        {"type": "outcome_resolved", "outcome": "success"},
        run_id="run-1",
        options=options,
        phase="output_validated",
        run=completed_run,
    )
    assert approval_sent is True
    assert outcome_sent is False
    assert send_mock.call_count == 1
    assert send_mock.call_args.args[0] == "Output approved"


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_sends_unpaired_output_approval(send_mock) -> None:
    options = NotificationOptions()
    running_run = {"status": "running", "phase": "whole_output_review"}
    sent = handle_audit_event(
        {"type": "whole_output_review_approved"},
        run_id="run-1",
        options=options,
        phase="whole_output_review",
        run=running_run,
    )
    assert sent is True
    assert send_mock.call_args.args[0] == "Output approved"


@patch("top_down_planning.notifications.bridge.send_desktop_notification")
def test_handle_audit_event_failed_pause_still_allows_limit_exceeded(send_mock) -> None:
    send_mock.side_effect = [False, True]
    options = NotificationOptions()
    state = NotificationDedupeState()
    handle_audit_event(
        {"type": "run_paused", "reason": "limit"},
        run_id="run-1",
        options=options,
        phase="planning",
        dedupe_state=state,
    )
    sent = handle_audit_event(
        {"type": "planning_limit_exceeded"},
        run_id="run-1",
        options=options,
        phase="planning",
        dedupe_state=state,
    )
    assert sent is True
    assert send_mock.call_count == 2
    assert state.last_run_paused_at is None


def test_unmapped_events_are_not_notified() -> None:
    options = NotificationOptions()
    with patch(
        "top_down_planning.notifications.bridge.send_desktop_notification",
        return_value=True,
    ) as send_mock:
        assert (
            handle_audit_event(
                {"type": "run_completed"},
                run_id="run-1",
                options=options,
            )
            is False
        )
        assert (
            handle_audit_event(
                {"type": "focused_review_failed"},
                run_id="run-1",
                options=options,
            )
            is False
        )
        send_mock.assert_not_called()


def _minimal_plan() -> Plan:
    return Plan(
        id="plan-run-abc",
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


@patch("top_down_planning.notifications.store.handle_audit_event", return_value=True)
def test_notifying_run_store_delegates_and_handles(handle_mock, tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True)
    run_id = "run-20260101T002201-002201"
    store.create_run(run_id, plan=_minimal_plan(), **create_run_kwargs(tmp_path))
    context = NotificationContext(options=NotificationOptions())
    wrapped = NotifyingRunStore(store, context)
    wrapped.append_event(run_id, {"type": "run_paused", "reason": "limit"})
    handle_mock.assert_called_once()
    events = store.load_events(run_id)
    assert events[-1]["type"] == "run_paused"


@patch("top_down_planning.notifications.store.handle_audit_event", side_effect=RuntimeError("boom"))
def test_notifying_run_store_append_event_is_fail_soft(handle_mock, tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True)
    run_id = "run-20260101T002201-002201"
    store.create_run(run_id, plan=_minimal_plan(), **create_run_kwargs(tmp_path))
    context = NotificationContext(options=NotificationOptions())
    wrapped = NotifyingRunStore(store, context)
    wrapped.append_event(run_id, {"type": "run_paused", "reason": "limit"})
    events = store.load_events(run_id)
    assert events[-1]["type"] == "run_paused"


def test_wrap_run_store_puts_notifications_outside_observability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True)
    wrapped = wrap_run_store(
        store,
        observability=ObservabilityContext(),
        notifications=NotificationContext(options=NotificationOptions()),
    )
    assert isinstance(wrapped, NotifyingRunStore)
    assert isinstance(wrapped._store, ObservingRunStore)


@patch("top_down_planning.notifications.outcome.send_desktop_notification", return_value=True)
def test_notify_run_outcome_cancelled(send_mock) -> None:
    notify_run_outcome(
        "cancelled",
        run_id="run-1",
        run={"phase": "planning", "status": "running"},
        options=NotificationOptions(),
    )
    send_mock.assert_called_once()
    assert send_mock.call_args.args[0] == "TDP run cancelled"


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_user_cancelled_notifies_when_terminal_disabled(send_mock) -> None:
    options = NotificationOptions(terminal=False)
    sent = handle_audit_event(
        {
            "type": "run_paused",
            "stop": {
                "code": "user_cancelled",
                "message": "cancelled by user",
            },
        },
        run_id="run-1",
        options=options,
        phase="planning",
    )
    assert sent is True
    assert send_mock.call_args.args[0] == "TDP run cancelled"


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_handle_audit_event_limit_pause_respects_disabled_terminal_tier(send_mock) -> None:
    options = NotificationOptions(terminal=False)
    assert (
        handle_audit_event(
            {
                "type": "run_paused",
                "stop": {
                    "code": "limit_exhausted",
                    "message": "planning limit reached",
                },
            },
            run_id="run-1",
            options=options,
            phase="planning",
        )
        is False
    )
    send_mock.assert_not_called()


@patch("top_down_planning.notifications.outcome.send_desktop_notification", return_value=True)
def test_notify_run_outcome_target_reached_when_running(send_mock) -> None:
    notify_run_outcome(
        "target_reached",
        run_id="run-1",
        run={"phase": "plan_validated", "status": "running"},
        options=NotificationOptions(terminal=False),
        until="plan",
    )
    send_mock.assert_called_once()


@patch("top_down_planning.notifications.outcome.send_desktop_notification", return_value=True)
def test_notify_run_outcome_target_reached_skips_terminal_status(send_mock) -> None:
    notify_run_outcome(
        "target_reached",
        run_id="run-1",
        run={"phase": "output_validated", "status": "completed"},
        options=NotificationOptions(),
        until="completed",
    )
    send_mock.assert_not_called()


@patch("top_down_planning.cli.user.notify_run_outcome")
@patch("top_down_planning.cli.user._build_run_engine")
def test_resume_single_step_does_not_emit_target_reached(
    build_engine,
    notify_mock,
    tmp_path: Path,
) -> None:
    from argparse import Namespace

    from top_down_planning.cli.user import handle_resume_command
    from top_down_planning.orchestrator.phases import PRODUCTION
    from tests.unit.test_resume_cli import _create_paused_production_run

    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    engine = build_engine.return_value
    engine.continue_run.return_value.ok = True
    engine.continue_run.return_value.phase = PRODUCTION
    engine.continue_run.return_value.status = "running"
    engine.continue_run.return_value.outcome = None
    engine.continue_run.return_value.steps = []
    engine.continue_run.return_value.reason = None
    engine.continue_run.return_value.cancelled = False

    with patch("top_down_planning.cli.user.emit_message"):
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=False,
                set=["limits.production.max_batches=99"],
                config=None,
                command="resume",
                until=None,
            )
        )

    notify_mock.assert_not_called()


@patch("top_down_planning.cli.user.notify_run_outcome")
@patch("top_down_planning.cli.user._build_run_engine")
def test_resume_until_emits_target_reached_when_still_running(
    build_engine,
    notify_mock,
    tmp_path: Path,
) -> None:
    from argparse import Namespace

    from top_down_planning.cli.user import handle_resume_command
    from top_down_planning.orchestrator.phases import PRODUCTION
    from tests.unit.test_resume_cli import _create_paused_production_run

    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    engine = build_engine.return_value
    engine.continue_run.return_value.ok = True
    engine.continue_run.return_value.phase = PRODUCTION
    engine.continue_run.return_value.status = "running"
    engine.continue_run.return_value.outcome = None
    engine.continue_run.return_value.steps = []
    engine.continue_run.return_value.reason = None
    engine.continue_run.return_value.cancelled = False

    with patch("top_down_planning.cli.user.emit_message"):
        handle_resume_command(
            Namespace(
                run=run_id,
                runs_dir=str(store.root),
                stream_json=False,
                check=False,
                set=["limits.production.max_batches=99"],
                config=None,
                command="resume",
                until="plan",
            )
        )

    notify_mock.assert_called_once()
    assert notify_mock.call_args.args[0] == "target_reached"


@patch("top_down_planning.notifications.desktop.send_desktop_notification", return_value=True)
def test_read_only_cli_commands_do_not_notify(send_mock, tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        """
run:
  output_goal: Goal.
runtime:
  runs_dir: .tdp/runs
""",
    )
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_id = "run-20260101T002201-003301"
    store = FileRunStore(runs_dir)
    store.create_run(run_id, plan=_minimal_plan(), **create_run_kwargs(tmp_path))

    run_cli(
        [
            "status",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--config",
            str(config_path),
        ]
    )
    run_cli(
        [
            "validate",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--config",
            str(config_path),
        ]
    )
    run_cli(
        [
            "inspect",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--config",
            str(config_path),
        ]
    )
    run_cli(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--check",
            "--config",
            str(config_path),
        ]
    )
    send_mock.assert_not_called()


@patch("top_down_planning.notifications.bridge.send_desktop_notification", return_value=True)
def test_run_cli_progress_notifications_with_stub_provider(send_mock, tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "run.yaml",
        """
run:
  output_goal: Deliver the sample output.
provider:
  name: stub
planning:
  max_depth: 4
""",
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    operations = with_root_contract(
        [
            {
                "op": "add_item",
                "temp_id": "item-api",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "API", "outcome": "API exists."},
            },
        ]
    )
    provider = StubProvider()
    provider.script_turn(
        done_events(signal="candidate_plan_ready", text="planning turn"),
        mutate_store=lambda: apply_plan(
            store,
            only_run_id(store),
            base_revision=0,
            operations=operations,
        )(),
    )

    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--runs-dir",
                str(runs_dir),
                "--set",
                "notifications.progress=true",
                "--stream-json",
            ]
        )

    assert result.exit_code == 0, result.stderr
    titles = [call.args[0] for call in send_mock.call_args_list]
    assert "Planning candidate ready" in titles
