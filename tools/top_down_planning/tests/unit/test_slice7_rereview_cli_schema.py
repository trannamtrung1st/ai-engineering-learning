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
from tests.unit.test_sub_tdp_attach_cli import _parent_with_orchestration


def _stdout_json(result: CliResult) -> dict:
    return json.loads(result.stdout)


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
