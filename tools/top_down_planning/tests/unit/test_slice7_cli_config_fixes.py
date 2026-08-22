"""Slice 7 continued-review regressions for CLI output and config contracts."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import top_down_planning.config as config_pkg
from top_down_planning.cli.execute import (
    _resolved_config_for_execute,
    parse_baseline_run_ids,
    parse_upstream_bindings,
)
from top_down_planning.config import ConfigError, DEFAULT_CONFIG, resolve_config
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.conftest import CliResult, run_cli
from tests.helpers import write_config
from tests.support.run_builders import _built_package
from tests.support.run_builders import _create_paused_production_run


def _stdout_json(result: CliResult) -> dict:
    """Structured stdout must be exactly one JSON document."""

    return json.loads(result.stdout)


def test_cli_result_json_rejects_multiple_top_level_documents() -> None:
    result = CliResult(
        exit_code=0,
        stdout='{"first": true}\n{"run_id": "run-1", "status": "running"}\n',
        stderr="",
    )

    with pytest.raises(json.JSONDecodeError):
        result.json()


def test_resume_stream_json_stdout_is_one_object_on_success(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    continuation = RunContinuationResult(
        ok=False,
        run_id=run_id,
        phase=PRODUCTION,
        status="paused",
        outcome=None,
        reason="limit reached",
        cancelled=False,
        target_reached=False,
    )
    engine = MagicMock()
    engine.continue_run.return_value = continuation

    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(
            ["resume", "--run", run_id, "--runs-dir", str(tmp_path), "--stream-json"]
        )

    payload = _stdout_json(result)
    assert result.exit_code == 1
    assert payload["ok"] is False
    assert payload["run_id"] == run_id
    assert "resume_plan" in payload
    assert payload["resume_plan"]["check_only"] is False


def test_resume_stream_json_single_step_stdout_is_one_object(tmp_path: Path) -> None:
    from top_down_planning.persistence import FileRunStore

    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    continuation = RunContinuationResult(
        ok=True,
        run_id=run_id,
        phase=PRODUCTION,
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=False,
    )
    engine = MagicMock()
    engine.continue_run.return_value = continuation

    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(
            ["resume", "--run", run_id, "--runs-dir", str(tmp_path), "--stream-json"]
        )

    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload["resume_plan"]["check_only"] is False


def test_prepare_human_and_structured_success_modes(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "prep.yaml",
        """
run:
  output_goal: Goal.
provider:
  name: stub
""",
    )
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "pkg"
    built = SimpleNamespace(
        package_id="pkg-prepare-1",
        manifest_path=output_dir / "manifest.json",
        manifest={
            "planning_run": {
                "approved_plan_revision": 0,
                "approved_plan_digest": "a" * 64,
            }
        },
    )
    continuation = SimpleNamespace(cancelled=False, reason=None)

    def _continue(run_id: str, until: str = "validated"):
        from top_down_planning.persistence import FileRunStore

        store = FileRunStore(runs_dir)
        run = store.load_run(run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["phase"] = PLAN_VALIDATED
        store.save_run(run_id, run, expected)
        return continuation

    engine = MagicMock()
    engine.continue_run.side_effect = _continue

    argv_base = [
        "prepare",
        "--config",
        str(config_path),
        "--runs-dir",
        str(runs_dir),
        "--output",
        str(output_dir),
    ]
    with (
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            return_value=built,
        ),
    ):
        human = run_cli(argv_base)
        structured = run_cli([*argv_base, "--stream-json"])

    assert human.exit_code == 0
    assert "pkg-prepare-1" in human.stdout
    assert human.stdout.strip()[0] != "{"
    payload = _stdout_json(structured)
    assert structured.exit_code == 0
    assert payload["ok"] is True
    assert payload["package_id"] == "pkg-prepare-1"


def test_execute_parent_only_human_and_structured_success(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    argv_base = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    with patch(
        "top_down_planning.orchestrator.prepared_run_factory.validate_resolved_config_against_package"
    ):
        human = run_cli(argv_base)
        structured = run_cli([*argv_base, "--stream-json"])

    assert human.exit_code == 0, human.stderr
    assert "parent-only" in human.stdout.lower() or "parent only" in human.stdout.lower()
    assert human.stdout.strip()[0] != "{"
    payload = _stdout_json(structured)
    assert structured.exit_code == 0
    assert payload["ok"] is True
    assert payload["parent_only"] is True


def test_execute_parent_and_unit_human_and_structured_success(tmp_path: Path) -> None:
    from tests.helpers import accept_child_run, create_run_kwargs
    from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory

    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    accept_child_run(store, child_id)

    continuation = RunContinuationResult(
        ok=True,
        run_id="unused",
        phase="production",
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=False,
    )
    engine = MagicMock()
    engine.continue_run.return_value = continuation
    argv_parent = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    argv_unit = [*argv_parent, "--unit", "item-foundation"]
    with (
        patch(
            "top_down_planning.orchestrator.prepared_run_factory.validate_resolved_config_against_package"
        ),
        patch("top_down_planning.cli.execute._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.execute.PreparedUnitExecutor.create_or_load_child_run",
            return_value=child_id,
        ),
    ):
        parent_human = run_cli(argv_parent)
        parent_json = run_cli([*argv_parent, "--stream-json"])
        unit_human = run_cli(argv_unit)
        unit_json = run_cli([*argv_unit, "--stream-json"])

    assert parent_human.exit_code == 0, parent_human.stderr
    assert parent_human.stdout.strip()[0] != "{"
    assert _stdout_json(parent_json)["ok"] is True
    assert unit_human.exit_code == 0, unit_human.stderr
    assert unit_human.stdout.strip()[0] != "{"
    unit_payload = _stdout_json(unit_json)
    assert unit_payload["ok"] is True
    assert unit_payload["unit_id"] == "item-foundation"


def test_execute_config_overlay_keeps_omitted_package_presentation(tmp_path: Path) -> None:
    package = SimpleNamespace(
        resolved_config={
            "planning": {"max_depth": 4},
            "observability": {
                "log_level": "verbose",
                "log_format": "jsonl",
                "color": "never",
                "show_agent_text": False,
                "show_timestamps": True,
                "agent_transcript": True,
            },
            "notifications": {
                "enabled": False,
                "terminal": False,
                "phase": True,
                "progress": True,
            },
            "runtime": {"runs_dir": "/from-package"},
        }
    )
    overlay = write_config(tmp_path / "exec.yaml", "runtime:\n  runs_dir: /from-overlay\n")
    resolved = _resolved_config_for_execute(
        Namespace(config=str(overlay), set=None),
        package,
    )
    assert resolved["notifications"]["enabled"] is False
    assert resolved["notifications"]["progress"] is True
    assert resolved["observability"]["log_level"] == "verbose"
    assert resolved["observability"]["agent_transcript"] is True
    assert resolved["planning"]["max_depth"] == 4
    assert resolved["runtime"]["runs_dir"] == "/from-overlay"


def test_execute_config_rejects_semantic_fields(tmp_path: Path) -> None:
    package = SimpleNamespace(resolved_config={"planning": {"max_depth": 4}})
    overlay = write_config(
        tmp_path / "semantic.yaml",
        "planning:\n  max_depth: 9\n",
    )
    with pytest.raises(ConfigError, match="not allowed"):
        _resolved_config_for_execute(
            Namespace(config=str(overlay), set=None),
            package,
        )


def test_execute_config_set_applies_after_sparse_overlay(tmp_path: Path) -> None:
    package = SimpleNamespace(
        resolved_config={
            "notifications": {
                "enabled": True,
                "terminal": True,
                "phase": True,
                "progress": True,
            },
            "runtime": {"runs_dir": "/from-package"},
        }
    )
    overlay = write_config(
        tmp_path / "exec.yaml",
        "notifications:\n  enabled: false\n",
    )
    resolved = _resolved_config_for_execute(
        Namespace(
            config=str(overlay),
            set=["notifications.progress=false", "runtime.runs_dir=/from-set"],
        ),
        package,
    )
    assert resolved["notifications"]["enabled"] is False
    assert resolved["notifications"]["terminal"] is True
    assert resolved["notifications"]["progress"] is False
    assert resolved["runtime"]["runs_dir"] == "/from-set"


def test_execute_cli_rejects_semantic_config_yaml(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    overlay = write_config(
        tmp_path / "semantic.yaml",
        "run:\n  output_goal: Drifted goal.\nprovider:\n  name: stub\n",
    )
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--parent-only",
            "--config",
            str(overlay),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 2
    payload = _stdout_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"


@pytest.mark.parametrize(
    ("yaml_body", "match"),
    [
        ("observability:\n  log_level: loud\n", "log_level"),
        ("observability:\n  log_format: yaml\n", "log_format"),
        ("observability:\n  color: rainbow\n", "color"),
        ("observability:\n  show_agent_text: 1\n", "boolean"),
        ("observability:\n  show_timestamps: 'false'\n", "boolean"),
        ("observability:\n  agent_transcript: 'false'\n", "boolean"),
        ("observability:\n  max_message_length: 0\n", ">= 1"),
        ("observability:\n  max_message_length: '5'\n", "positive integer"),
        ("observability:\n  max_tool_summary_length: -1\n", ">= 1"),
        ("observability:\n  max_tool_summary_length: 1.5\n", "positive integer"),
        ("notifications:\n  enabled: 'false'\n", "boolean"),
        ("notifications:\n  terminal: 1\n", "boolean"),
        ("notifications:\n  phase: null\n", "boolean"),
        ("notifications:\n  progress: 'true'\n", "boolean"),
    ],
)
def test_resolve_config_rejects_invalid_presentation_types(
    tmp_path: Path, yaml_body: str, match: str
) -> None:
    path = write_config(
        tmp_path / "bad.yaml",
        f"run:\n  output_goal: Goal.\n{yaml_body}",
    )
    with pytest.raises(ConfigError, match=match):
        resolve_config(path)


def test_cli_truncation_flags_reject_non_positive_human_and_json(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "run.yaml", "run:\n  output_goal: Goal.\n")
    for flag, value, stream_json in (
        ("--max-message-length", "0", True),
        ("--max-message-length", "-1", False),
        ("--max-tool-summary-length", "0", True),
        ("--max-tool-summary-length", "-1", False),
    ):
        argv = [
            "status",
            "--run",
            "run-20260101T000001-000001",
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            flag,
            value,
        ]
        if stream_json:
            argv.append("--stream-json")
        result = run_cli(argv)
        assert result.exit_code == 2
        if stream_json:
            payload = _stdout_json(result)
            assert payload["ok"] is False
            assert payload["error"]["code"] == "usage_error"
        else:
            assert result.stdout.strip() == "" or "{" not in result.stdout.split("\n", 1)[0]


def test_parser_failures_emit_structured_usage_errors() -> None:
    cases = (
        ["execute", "--stream-json"],
        ["execute", "--manifest", "manifest.json", "--until", "nope", "--stream-json"],
        ["status", "--unknown-flag", "--stream-json"],
        ["status", "--log-level", "loud", "--stream-json"],
        ["sub-tdp", "attach", "--stream-json"],
        ["status", "--max-message-length", "abc", "--stream-json"],
        ["resume", "--color", "rainbow", "--stream-json"],
    )
    for argv in cases:
        result = run_cli(argv)
        assert result.exit_code == 2, argv
        payload = _stdout_json(result)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "usage_error"


def test_execute_malformed_upstream_and_baseline_are_usage_errors(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    with pytest.raises(ValueError, match="expected unit_id=run_id"):
        parse_upstream_bindings(["not-a-binding"])
    with pytest.raises(ValueError, match="duplicate"):
        parse_upstream_bindings(
            [
                "item-a=run-20260101T000001-000001",
                "item-a=run-20260101T000002-000002",
            ]
        )
    with pytest.raises(ValueError):
        parse_baseline_run_ids([" "])
    with pytest.raises(ValueError, match="duplicate"):
        parse_baseline_run_ids(
            ["run-20260101T000001-000001", "run-20260101T000001-000001"]
        )

    common = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--unit",
        "item-foundation",
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    malformed_upstream = run_cli([*common, "--upstream", "no-equals"])
    assert malformed_upstream.exit_code == 2
    upstream_payload = _stdout_json(malformed_upstream)
    assert upstream_payload["error"]["code"] == "sub_tdp_upstream_invalid"

    malformed_baseline = run_cli([*common, "--baseline", " "])
    assert malformed_baseline.exit_code == 2
    baseline_payload = _stdout_json(malformed_baseline)
    assert baseline_payload["error"]["code"] == "sub_tdp_baseline_invalid"

    empty_upstream = run_cli([*common, "--upstream", "item-foundation="])
    assert empty_upstream.exit_code == 2
    assert _stdout_json(empty_upstream)["error"]["code"] == "sub_tdp_upstream_invalid"

    duplicate_upstream = run_cli(
        [
            *common,
            "--upstream",
            "item-a=run-20260101T000001-000001",
            "--upstream",
            "item-a=run-20260101T000002-000002",
        ]
    )
    assert duplicate_upstream.exit_code == 2
    assert _stdout_json(duplicate_upstream)["error"]["code"] == "sub_tdp_upstream_invalid"

    duplicate_baseline = run_cli(
        [*common, "--baseline", "run-20260101T000001-000001", "--baseline", "run-20260101T000001-000001"]
    )
    assert duplicate_baseline.exit_code == 2
    assert _stdout_json(duplicate_baseline)["error"]["code"] == "sub_tdp_baseline_invalid"

    parent_argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    baseline_without_unit = run_cli([*parent_argv, "--baseline", "run-20260101T000001-000001"])
    assert baseline_without_unit.exit_code == 2
    assert _stdout_json(baseline_without_unit)["error"]["code"] == "sub_tdp_baseline_invalid"

    unit_and_parent_only = run_cli([*common, "--parent-only"])
    assert unit_and_parent_only.exit_code == 2
    assert _stdout_json(unit_and_parent_only)["error"]["code"] == "invalid_execute_options"


def test_doctor_and_attach_normalize_store_config_and_run_errors(tmp_path: Path) -> None:
    missing_store = tmp_path / "no-store"
    missing_run = "run-20260101T111111-abcdef"
    malformed_id = "not-a-run-id"
    bad_config = write_config(tmp_path / "bad.yaml", "plannig:\n  max_depth: 3\n")
    (tmp_path / "empty-store").mkdir()

    doctor_missing_store = run_cli(
        ["doctor", "--runs-dir", str(missing_store), "--stream-json"]
    )
    assert doctor_missing_store.exit_code == 1
    assert _stdout_json(doctor_missing_store)["error"]["code"] == "runs_store_not_found"

    doctor_bad_config = run_cli(
        ["doctor", "--config", str(bad_config), "--stream-json"]
    )
    assert doctor_bad_config.exit_code == 2
    assert _stdout_json(doctor_bad_config)["error"]["code"] == "config_error"

    doctor_missing_run = run_cli(
        [
            "doctor",
            "--run",
            missing_run,
            "--runs-dir",
            str(tmp_path / "empty-store"),
            "--stream-json",
        ]
    )
    assert doctor_missing_run.exit_code == 1
    assert _stdout_json(doctor_missing_run)["error"]["code"] == "run_not_found"

    doctor_bad_id = run_cli(
        [
            "doctor",
            "--run",
            malformed_id,
            "--runs-dir",
            str(tmp_path / "empty-store"),
            "--stream-json",
        ]
    )
    assert doctor_bad_id.exit_code == 2
    assert _stdout_json(doctor_bad_id)["error"]["code"] == "invalid_run_id"

    attach_missing_store = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            missing_run,
            "--child",
            missing_run,
            "--runs-dir",
            str(missing_store),
            "--stream-json",
        ]
    )
    assert attach_missing_store.exit_code == 1
    assert _stdout_json(attach_missing_store)["error"]["code"] == "runs_store_not_found"

    attach_bad_id = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            malformed_id,
            "--child",
            missing_run,
            "--runs-dir",
            str(tmp_path / "empty-store"),
            "--stream-json",
        ]
    )
    assert attach_bad_id.exit_code == 2
    assert _stdout_json(attach_bad_id)["error"]["code"] == "invalid_run_id"

    human_missing = run_cli(["doctor", "--runs-dir", str(missing_store)])
    assert human_missing.exit_code == 1
    assert "runs store not found" in human_missing.stderr.lower()

    doctor_human_bad_id = run_cli(
        [
            "doctor",
            "--run",
            malformed_id,
            "--runs-dir",
            str(tmp_path / "empty-store"),
        ]
    )
    assert doctor_human_bad_id.exit_code == 2
    assert doctor_human_bad_id.stdout.strip() == "" or doctor_human_bad_id.stderr

    attach_bad_config = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            missing_run,
            "--child",
            missing_run,
            "--config",
            str(bad_config),
            "--stream-json",
        ]
    )
    assert attach_bad_config.exit_code == 2
    assert _stdout_json(attach_bad_config)["error"]["code"] == "config_error"

    attach_missing_run = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            missing_run,
            "--child",
            missing_run,
            "--runs-dir",
            str(tmp_path / "empty-store"),
            "--stream-json",
        ]
    )
    assert attach_missing_run.exit_code == 1
    assert _stdout_json(attach_missing_run)["error"]["code"] in {
        "run_not_found",
        "sub_tdp_attach_rejected",
    }

    attach_human_store = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            missing_run,
            "--child",
            missing_run,
            "--runs-dir",
            str(missing_store),
        ]
    )
    assert attach_human_store.exit_code == 1
    assert "runs store not found" in attach_human_store.stderr.lower()


def test_doctor_fix_nonzero_exit_when_repair_incomplete(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.agent_process_cleanup import OrphanCleanupResult
    from top_down_planning.persistence import FileRunStore
    from tests.helpers import create_run_kwargs, minimal_resolved_config
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.orchestrator.phases import PLANNING

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T070101-070101"
    store.create_run(
        run_id,
        plan=Plan(
            id="plan-doc",
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
        ),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "running"
    store.save_run(run_id, run, expected)

    with (
        patch("top_down_planning.cli.doctor.is_run_orchestrator_alive", return_value=False),
        patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(4242,)),
        ),
    ):
        structured = run_cli(
            ["doctor", "--fix", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        )
        human = run_cli(
            ["doctor", "--fix", "--run", run_id, "--runs-dir", str(store.root)]
        )

    assert structured.exit_code == 1
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert human.exit_code == 1


def test_sub_tdp_attach_human_success_mode(tmp_path: Path) -> None:
    from tests.helpers import accept_child_run
    from tests.support.run_builders import _parent_with_orchestration
    from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor

    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)
    argv = [
        "sub-tdp",
        "attach",
        "--parent",
        parent_id,
        "--child",
        child_id,
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    human = run_cli(argv)
    structured = run_cli([*argv, "--stream-json"])
    assert human.exit_code == 0, human.stderr
    assert parent_id in human.stdout
    assert child_id in human.stdout
    assert human.stdout.strip()[0] != "{"
    payload = _stdout_json(structured)
    assert payload["ok"] is True
    assert payload["parent_run_id"] == parent_id


def test_prepare_and_execute_help_does_not_advertise_default_runs_dir() -> None:
    prepare_help = run_cli(["prepare", "--help"])
    execute_help = run_cli(["execute", "--help"])
    status_help = run_cli(["status", "--help"])
    run_help = run_cli(["run", "--help"])
    for result in (prepare_help, execute_help, status_help, run_help):
        assert result.exit_code == 0
    assert "does not fall back to ./runs" in prepare_help.stdout
    assert "does not fall back to ./runs" in execute_help.stdout
    assert "does not fall back to ./runs" in run_help.stdout
    assert "does not fall back to ./runs" not in status_help.stdout
    assert "./runs" in status_help.stdout


def test_config_package_all_exports_exist() -> None:
    for name in config_pkg.__all__:
        assert hasattr(config_pkg, name), name


def test_provider_idle_timeout_default_matches_documented_contract() -> None:
    assert DEFAULT_CONFIG["limits"]["provider"]["turn_idle_timeout_seconds"] == 2.0
    assert DEFAULT_CONFIG["limits"]["provider"]["max_stream_json_record_bytes"] == 1048576
    assert (
        resolve_config(None)["limits"]["provider"]["max_stream_json_record_bytes"]
        == 1048576
    )
    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "default `0`, disabled" not in text
    assert "default `2`" in text or "default 2" in text


def test_stream_json_commands_emit_one_json_document() -> None:
    cases = (
        ["run", "--stream-json"],
        ["prepare", "--stream-json"],
        ["execute", "--stream-json"],
        ["resume", "--stream-json"],
        ["status", "--stream-json"],
        ["inspect", "--stream-json"],
        ["validate", "--stream-json"],
        ["doctor", "--runs-dir", "/missing-tdp-store", "--stream-json"],
        ["sub-tdp", "attach", "--stream-json"],
    )
    for argv in cases:
        result = run_cli(argv)
        payload = _stdout_json(result)
        assert payload["ok"] is False
        assert "error" in payload


def test_resume_until_stream_json_stdout_is_one_object(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    continuation = RunContinuationResult(
        ok=True,
        run_id=run_id,
        phase=PRODUCTION,
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=True,
    )
    engine = MagicMock()
    engine.continue_run.return_value = continuation
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(
            [
                "resume",
                "--run",
                run_id,
                "--until",
                "completed",
                "--runs-dir",
                str(tmp_path),
                "--stream-json",
            ]
        )
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload["until"] == "completed"
    assert payload["resume_plan"]["check_only"] is False
