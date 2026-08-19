"""Slice 7 continued-review regressions for run access taxonomy and schema."""

from __future__ import annotations

import json
import shutil
from argparse import Namespace
from pathlib import Path

import pytest

from top_down_planning.cli.execute import _resolved_config_for_execute
from top_down_planning.config import ConfigError, resolve_config
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.package.digests import digest_plan_file
from top_down_planning.persistence import FileRunStore
from tests.conftest import CliResult, run_cli
from tests.helpers import create_run_kwargs, minimal_resolved_config, write_config
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_sub_tdp_attach_cli import _parent_with_orchestration


def _stdout_json(result: CliResult) -> dict:
    return json.loads(result.stdout)


def _wipe_txn_dirs(run_dir: Path) -> None:
    for child in list(run_dir.iterdir()):
        if child.name.startswith("."):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def _create_planning_run(store: FileRunStore, run_id: str) -> str:
    store.create_run(
        run_id,
        plan=Plan(
            id="plan-slice7",
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
    return run_id


def test_run_help_does_not_advertise_default_runs_dir() -> None:
    run_help = run_cli(["run", "--help"])
    prepare_help = run_cli(["prepare", "--help"])
    status_help = run_cli(["status", "--help"])

    assert run_help.exit_code == 0
    assert "does not fall back to ./runs" in run_help.stdout
    assert "does not fall back to ./runs" in prepare_help.stdout
    assert "does not fall back to ./runs" not in status_help.stdout
    assert "./runs" in status_help.stdout


@pytest.mark.parametrize(
    ("command", "artifact"),
    [
        ("status", "run.json"),
        ("status", "plan.json"),
        ("inspect", "plan.json"),
        ("inspect", "resolved-config.yaml"),
        ("validate", "run.json"),
        ("validate", "plan.json"),
        ("validate", "production.json"),
        ("validate", "resolved-config.yaml"),
        ("resume", "run.json"),
        ("doctor", "run.json"),
    ],
)
def test_corrupt_run_artifacts_emit_stable_cli_errors(
    tmp_path: Path, command: str, artifact: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T081101-081101")
    run_dir = store.run_dir(run_id)
    for child in list(run_dir.iterdir()):
        if child.name.startswith("."):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    target = run_dir / artifact
    if artifact.endswith(".yaml"):
        target.write_text(": not a mapping\n[", encoding="utf-8")
    else:
        target.write_text("{not-json", encoding="utf-8")

    argv = [command, "--run", run_id, "--runs-dir", str(store.root)]
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)

    assert structured.exit_code == 1
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "corrupt_run"
    assert human.exit_code == 1
    assert "Traceback" not in human.stderr
    assert "Traceback" not in human.stdout


def _rewrite_json_file_as_utf16(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_bytes(json.dumps(payload).encode("utf-16"))


@pytest.mark.parametrize("command", ["status", "inspect", "validate", "resume"])
@pytest.mark.parametrize("artifact", ["run.json", "plan.json"])
def test_utf16_canonical_json_is_corrupt_run_for_user_commands(
    tmp_path: Path, command: str, artifact: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T081401-081401")
    if command == "resume":
        _pause_run(store, run_id)
    run_dir = store.run_dir(run_id)
    _wipe_txn_dirs(run_dir)
    _rewrite_json_file_as_utf16(run_dir / artifact)

    argv = [command, "--run", run_id, "--runs-dir", str(store.root)]
    if command == "resume":
        argv.append("--check")
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)

    assert structured.exit_code == 1
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "corrupt_run"
    assert "Traceback" not in structured.stderr
    assert "Traceback" not in structured.stdout
    assert human.exit_code == 1
    assert "Traceback" not in human.stderr
    assert "Traceback" not in human.stdout
    assert human.stderr.strip()


@pytest.mark.parametrize("command", ["status", "inspect", "validate", "resume"])
def test_malformed_run_ids_are_usage_errors_for_user_commands(
    tmp_path: Path, command: str
) -> None:
    store_root = tmp_path / "runs"
    store_root.mkdir()
    argv = [command, "--run", "not-a-run-id", "--runs-dir", str(store_root)]
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)

    assert structured.exit_code == 2
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_run_id"
    assert human.exit_code == 2
    assert "Traceback" not in human.stderr
    assert "Traceback" not in human.stdout


def test_sub_tdp_attach_normalizes_corrupt_execution_packages(tmp_path: Path) -> None:
    store, parent_id, package, _config = _parent_with_orchestration(tmp_path)
    child_id = "run-20260101T081201-081201"
    _create_planning_run(store, child_id)
    common = [
        "sub-tdp",
        "attach",
        "--parent",
        parent_id,
        "--child",
        child_id,
        "--runs-dir",
        str(tmp_path / "runs"),
    ]

    def _assert_package_error(result: CliResult) -> None:
        assert result.exit_code == 1
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout

    original = package.manifest_path.read_text(encoding="utf-8")
    package.manifest_path.write_text("{not-json", encoding="utf-8")
    malformed_json = run_cli([*common, "--stream-json"])
    malformed_human = run_cli(common)
    _assert_package_error(malformed_json)
    _assert_package_error(malformed_human)
    payload = _stdout_json(malformed_json)
    assert payload["ok"] is False
    assert payload["error"]["code"] in {"sub_tdp_attach_rejected", "package_json_invalid"}

    package.manifest_path.write_text(original, encoding="utf-8")
    manifest = json.loads(original)
    manifest["package_digest"] = "sha256:" + ("0" * 64)
    package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest_mismatch = run_cli([*common, "--stream-json"])
    digest_human = run_cli(common)
    _assert_package_error(digest_mismatch)
    _assert_package_error(digest_human)
    assert _stdout_json(digest_mismatch)["ok"] is False
    assert _stdout_json(digest_mismatch)["error"]["code"] in {
        "sub_tdp_attach_rejected",
        "package_invalid",
    }

    package.manifest_path.write_text(original, encoding="utf-8")
    parent_plan_path = Path(package.manifest_path.parent / manifest["parent"]["plan_file"])
    parent_plan_path.write_text("{}", encoding="utf-8")
    manifest = json.loads(original)
    manifest["parent"]["plan_digest"] = digest_plan_file(parent_plan_path)
    package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    invalid_content = run_cli([*common, "--stream-json"])
    invalid_human = run_cli(common)
    _assert_package_error(invalid_content)
    _assert_package_error(invalid_human)
    assert _stdout_json(invalid_content)["ok"] is False
    assert _stdout_json(invalid_content)["error"]["code"] in {
        "sub_tdp_attach_rejected",
        "package_plan_invalid",
        "package_invalid",
    }


@pytest.mark.parametrize(
    "yaml_body",
    [
        "observability:\n  log_leveel: verbose\n",
        "observability:\n  foo: 1\n",
        "notifications:\n  enabld: true\n",
    ],
)
def test_execute_config_rejects_unknown_presentation_fields(
    tmp_path: Path, yaml_body: str
) -> None:
    from types import SimpleNamespace

    overlay = write_config(tmp_path / "overlay.yaml", yaml_body)
    with pytest.raises(ConfigError, match="not allowed"):
        _resolved_config_for_execute(
            Namespace(config=str(overlay), set=None),
            SimpleNamespace(resolved_config={"observability": {"log_level": "normal"}}),
        )


@pytest.mark.parametrize(
    ("yaml_body", "set_override"),
    [
        ("run:\n  output_goal: 12\n", None),
        ("run:\n  input_refs: {}\n  output_goal: Goal.\n", None),
        ("run:\n  output_goal: Goal.\nplanning:\n  max_depth: '4'\n", None),
        ("run:\n  output_goal: Goal.\nreview:\n  focused_plan:\n    enabled: 1\n", None),
        ("run:\n  output_goal: Goal.\nprovider:\n  name: claude\n", None),
        ("run:\n  output_goal: Goal.\nruntime:\n  runs_dir: 2\n", None),
        ("run:\n  output_goal: Goal.\n", "planning.max_depth=not-an-int"),
        ("run:\n  output_goal: Goal.\n", "review.focused_plan.enabled=1"),
    ],
)
def test_resolve_config_rejects_schema_invalid_types(
    tmp_path: Path, yaml_body: str, set_override: str | None
) -> None:
    path = write_config(tmp_path / "cfg.yaml", yaml_body)
    overrides = [set_override] if set_override else None
    with pytest.raises(ConfigError):
        resolve_config(path, overrides)


def _pause_run(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PLANNING,
        "message": "paused for tests",
        "role": None,
        "details": {},
    }
    store.save_run(run_id, run, expected)


def _assert_corrupt_run(result: CliResult) -> None:
    assert result.exit_code == 1
    if "--stream-json" in str(result):
        pass
    payload = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    if payload is not None:
        assert payload["ok"] is False
        assert payload["error"]["code"] == "corrupt_run"
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_semantic_plan_corruption_is_corrupt_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T091101-091101")
    plan_path = store.run_dir(run_id) / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    items = list(plan["items"])
    items.append(dict(items[0]))
    plan["items"] = items
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    for command in ("status", "inspect", "validate"):
        result = run_cli(
            [command, "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        )
        _assert_corrupt_run(result)


def test_semantic_review_corruption_is_corrupt_run_on_validate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T091201-091201")
    reviews_dir = store.reviews_dir(run_id)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (reviews_dir / "rev-bad.json").write_text(
        json.dumps({"id": "rev-bad", "findings": "not-a-list"}),
        encoding="utf-8",
    )

    result = run_cli(
        ["validate", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    _assert_corrupt_run(result)


@pytest.mark.parametrize("artifact", ["resolved-config.yaml", "plan.json", "production.json"])
def test_resume_later_store_reads_normalize_corrupt_run(
    tmp_path: Path, artifact: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T091301-091301")
    _pause_run(store, run_id)
    target = store.run_dir(run_id) / artifact
    if artifact.endswith(".yaml"):
        target.write_text(": not a mapping\n[", encoding="utf-8")
    else:
        target.write_text("{not-json", encoding="utf-8")

    result = run_cli(
        ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    _assert_corrupt_run(result)


def test_parent_status_missing_and_corrupt_production(tmp_path: Path) -> None:
    store, parent_id, _package, _config = _parent_with_orchestration(tmp_path)
    production_path = store.run_dir(parent_id) / "production.json"
    production_path.unlink()
    _wipe_txn_dirs(store.run_dir(parent_id))
    missing = run_cli(
        ["status", "--run", parent_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    _assert_corrupt_run(missing)

    store, parent_id, _package, _config = _parent_with_orchestration(tmp_path / "second")
    (store.run_dir(parent_id) / "production.json").write_text("{not-json", encoding="utf-8")
    _wipe_txn_dirs(store.run_dir(parent_id))
    corrupt = run_cli(
        ["status", "--run", parent_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    _assert_corrupt_run(corrupt)


@pytest.mark.parametrize(
    ("yaml_body", "set_override"),
    [
        ("run:\n  output_goal: Goal.\nproject:\n  workspace: 123\n", None),
        ("run:\n  output_goal: Goal.\nproject:\n  workspace: null\n", None),
        ("run:\n  output_goal: Goal.\n", "project.workspace=[]"),
    ],
)
def test_resolve_config_rejects_invalid_project_workspace_before_coercion(
    tmp_path: Path, yaml_body: str, set_override: str | None
) -> None:
    path = write_config(tmp_path / "ws.yaml", yaml_body)
    overrides = [set_override] if set_override else None
    with pytest.raises(ConfigError, match="workspace"):
        resolve_config(path, overrides)


def test_execute_rejects_non_string_runtime_runs_dir(tmp_path: Path) -> None:
    from types import SimpleNamespace

    package = SimpleNamespace(
        resolved_config={
            "observability": {"log_level": "normal"},
            "runtime": {"runs_dir": "/from-package"},
        }
    )
    overlay = write_config(tmp_path / "runtime.yaml", "runtime:\n  runs_dir: 2\n")
    with pytest.raises(ConfigError, match="runtime.runs_dir"):
        _resolved_config_for_execute(
            Namespace(config=str(overlay), set=None),
            package,
        )
    with pytest.raises(ConfigError, match="runtime.runs_dir"):
        _resolved_config_for_execute(
            Namespace(config=None, set=["runtime.runs_dir=2"]),
            package,
        )


def test_execute_upstream_and_baseline_reject_noncanonical_run_ids(tmp_path: Path) -> None:
    from top_down_planning.cli.execute import parse_baseline_run_ids, parse_upstream_bindings

    with pytest.raises(ValueError):
        parse_upstream_bindings(["item-foundation=run-1"])
    with pytest.raises(ValueError):
        parse_upstream_bindings(["item-foundation=../run-x"])
    with pytest.raises(ValueError):
        parse_upstream_bindings(["item-foundation= run-20260101T000001-000001"])
    with pytest.raises(ValueError):
        parse_baseline_run_ids(["run-1"])
    with pytest.raises(ValueError):
        parse_baseline_run_ids(["../run-x"])
    with pytest.raises(ValueError):
        parse_baseline_run_ids([" run-20260101T000001-000001"])

    _, _, package = _built_package(tmp_path)
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
    upstream = run_cli([*common, "--upstream", "item-foundation=run-1"])
    assert upstream.exit_code == 2
    assert json.loads(upstream.stdout)["error"]["code"] == "sub_tdp_upstream_invalid"
    human_up = run_cli(
        [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--unit",
            "item-foundation",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--upstream",
            "item-foundation=run-1",
        ]
    )
    assert human_up.exit_code == 2
    assert "Traceback" not in human_up.stderr

    baseline = run_cli([*common, "--baseline", "../run-x"])
    assert baseline.exit_code == 2
    assert json.loads(baseline.stdout)["error"]["code"] == "sub_tdp_baseline_invalid"


def test_cli_run_id_validator_rejects_surrounding_whitespace(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T091401-091401")
    result = run_cli(
        [
            "status",
            "--run",
            f" {run_id} ",
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_run_id"


def test_doctor_fix_nonzero_when_requested_repairs_do_not_complete(tmp_path: Path) -> None:
    from unittest.mock import patch

    from core_tools.persistence import exclusive_file_lock
    from top_down_planning.domain.run_ownership import RunOwnershipError

    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T091501-091501")
    _pause_run(store, run_id)

    creating = store.root / ".creating-run-20260101T091511-091511"
    creating.mkdir()
    creating_lock = store.root / ".creating-run-20260101T091511-091511.lock"
    with exclusive_file_lock(creating_lock):
        creating_result = run_cli(
            ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
        )
    assert creating_result.exit_code == 1
    creating_payload = json.loads(creating_result.stdout)
    assert creating_payload["ok"] is False

    stage = store.run_dir(run_id) / ".stage-leftover"
    stage.mkdir()
    commit_lock = store.run_dir(run_id) / ".commit.lock"
    with exclusive_file_lock(commit_lock):
        txn_result = run_cli(
            ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
        )
    assert txn_result.exit_code == 1
    assert json.loads(txn_result.stdout)["ok"] is False

    running = store.load_run(run_id)
    expected = int(running["revision"])
    running = dict(running)
    running["revision"] = expected + 1
    running["status"] = "running"
    running["stop"] = None
    store.save_run(run_id, running, expected)
    with (
        patch(
            "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
            return_value=False,
        ),
        patch("top_down_planning.cli.doctor.is_run_orchestrator_alive", return_value=False),
        patch(
            "top_down_planning.cli.doctor.run_ownership",
            side_effect=RunOwnershipError("owned elsewhere"),
        ),
    ):
        refused = run_cli(
            ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
        )
    assert refused.exit_code == 1
    refused_payload = json.loads(refused.stdout)
    assert refused_payload["ok"] is False
    assert run_id in refused_payload.get("repair_refused_run_ids", [])


def test_doctor_human_reports_commit_transaction_dirs(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir()
    empty = run_cli(["doctor", "--runs-dir", str(store.root)])
    assert empty.exit_code == 0
    assert "commit transaction dirs: none" in empty.stdout

    run_id = _create_planning_run(store, "run-20260101T091601-091601")
    _pause_run(store, run_id)
    (store.run_dir(run_id) / ".stage-leftover").mkdir()
    present = run_cli(["doctor", "--runs-dir", str(store.root)])
    assert present.exit_code == 0
    assert ".stage-leftover" in present.stdout
    structured = run_cli(
        ["doctor", "--runs-dir", str(store.root), "--stream-json"]
    )
    payload = json.loads(structured.stdout)
    assert any(".stage-leftover" in item for item in payload["workspace"]["commit_transaction_dirs"])
