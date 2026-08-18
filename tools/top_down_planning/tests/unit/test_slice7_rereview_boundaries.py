"""Slice 7 re-review: operational I/O, persisted config, package, and doctor artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import dump_yaml, load_yaml
from top_down_planning.config import resolve_config
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.package.digests import compute_package_digest
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs, write_config
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_slice7_rereview_cli_schema import (
    _create_planning_run,
    _pause_run,
    _wipe_txn_dirs,
)
from tests.unit.test_slice7_rereview_config_ops import (
    _assert_operational_error,
    _minimal_run_yaml,
)
from tests.unit.test_sub_tdp_attach_cli import _parent_with_orchestration


def _assert_both_modes(argv: list[str], *, code: str, exit_code: int) -> None:
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)
    assert structured.exit_code == exit_code
    assert human.exit_code == exit_code
    assert "Traceback" not in structured.stderr
    assert "Traceback" not in structured.stdout
    assert "Traceback" not in human.stderr
    assert "Traceback" not in human.stdout
    payload = json.loads(structured.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def _assert_corrupt_both(argv: list[str]) -> None:
    _assert_both_modes(argv, code="corrupt_run", exit_code=1)


def _assert_operational_both(argv: list[str]) -> None:
    _assert_operational_error(run_cli([*argv, "--stream-json"]), structured=True)
    _assert_operational_error(run_cli(argv), structured=False)


def _rewrite_resolved_config_yaml(run_dir: Path, mutate) -> None:
    path = run_dir / "resolved-config.yaml"
    payload = load_yaml(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(dump_yaml(payload), encoding="utf-8")
    _wipe_txn_dirs(run_dir)


def _recompute_package_digest(manifest: dict) -> None:
    context = manifest.get("context") or {}
    context_digests = {
        key: str(value)
        for key, value in context.items()
        if str(key).endswith("_digest") and value
    }
    manifest["package_digest"] = compute_package_digest(
        manifest,
        parent_plan_digest=str((manifest.get("parent") or {}).get("plan_digest") or ""),
        unit_plan_digests=[
            str(unit.get("plan_digest") or "")
            for unit in (manifest.get("units") or [])
        ],
        approved_plan_digest=str(
            (manifest.get("planning_run") or {}).get("approved_plan_digest") or ""
        ),
        context_digests=context_digests,
    )


def _tamper_embedded_config(package, mutate) -> None:
    config_path = package.manifest_path.parent / "execution" / "resolved_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mutate(config)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    manifest_path = package.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["context"]["config_contract_digest"] = compute_config_contract_digest(config)
    manifest["context"]["config_execution_digest"] = compute_config_execution_digest(
        config
    )
    _recompute_package_digest(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_colon_named_workspace_resource_round_trips_through_create_run(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a:b.md").write_text("colon name\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "colon.yaml",
            _minimal_run_yaml(
                workspace,
                "agent_context:\n  roles:\n    producer:\n      resources:\n"
                '        - "a:b.md"\n',
            ),
        ),
        cwd=workspace,
    )
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    assert "a:b.md" in kwargs["context_snapshot_binding"]["resource_digests"]

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111002-111002"
    store.create_run(
        run_id,
        plan=Plan(
            id="plan-colon",
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
        **kwargs,
    )
    reloaded = store.load_run(run_id)
    assert "a:b.md" in reloaded["context_snapshot_binding"]["resource_digests"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda cfg: cfg["planning"].__setitem__("max_depth", "bad"),
        lambda cfg: cfg.setdefault("observability", {}).__setitem__(
            "show_agent_text", 1
        ),
        lambda cfg: cfg.setdefault("runtime", {}).__setitem__("runs_dir", 2),
        lambda cfg: cfg["review"]["focused_plan"].__setitem__("enabled", 1),
        lambda cfg: cfg["provider"].__setitem__("name", "not-a-provider"),
    ],
)
def test_schema_invalid_persisted_resolved_config_is_corrupt_run(
    tmp_path: Path, mutate
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T111101-111101")
    _pause_run(store, run_id)
    _rewrite_resolved_config_yaml(store.run_dir(run_id), mutate)
    runs = str(store.root)
    _assert_corrupt_both(["inspect", "--run", run_id, "--runs-dir", runs])
    _assert_corrupt_both(["validate", "--run", run_id, "--runs-dir", runs])
    _assert_corrupt_both(["resume", "--run", run_id, "--runs-dir", runs, "--check"])


def test_run_create_and_event_oserror_are_operational(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = write_config(tmp_path / "ops.yaml", _minimal_run_yaml(workspace))
    argv = ["run", "--config", str(cfg), "--runs-dir", str(tmp_path / "runs")]

    with patch.object(FileRunStore, "create_run", side_effect=OSError("disk full")):
        _assert_operational_both(argv)

    created = {"n": 0}
    original_create = FileRunStore.create_run

    def _create(self, *args, **kwargs):
        created["n"] += 1
        return original_create(self, *args, **kwargs)

    with (
        patch.object(FileRunStore, "create_run", _create),
        patch.object(FileRunStore, "append_event", side_effect=OSError("journal full")),
    ):
        _assert_operational_both(argv)
    assert created["n"] >= 1


def test_prepare_create_and_event_oserror_are_operational(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = write_config(tmp_path / "prep.yaml", _minimal_run_yaml(workspace))
    argv = [
        "prepare",
        "--config",
        str(cfg),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--output",
        str(tmp_path / "pkg"),
    ]
    with patch.object(FileRunStore, "create_run", side_effect=OSError("disk full")):
        _assert_operational_both(argv)
    with patch.object(FileRunStore, "append_event", side_effect=OSError("journal full")):
        _assert_operational_both(argv)


def test_execute_save_oserror_is_operational(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    with patch.object(FileRunStore, "create_run", side_effect=OSError("disk full")):
        _assert_operational_both(argv)
    with patch.object(FileRunStore, "save_production", side_effect=OSError("disk full")):
        _assert_operational_both(argv)


def test_resume_commit_oserror_is_operational(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T111201-111201")
    _pause_run(store, run_id)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    stop = dict(run.get("stop") or {})
    stop["details"] = {
        "limit": "limits.planning.max_agent_turns",
        "consumed": 1,
        "configured": 1,
    }
    run["stop"] = stop
    store.save_run(run_id, run, expected)
    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    with patch(
        "top_down_planning.cli.user.apply_resume_plan_atomically",
        side_effect=OSError("disk full"),
    ):
        _assert_operational_both(argv)


def test_doctor_fix_cleanup_oserror_is_operational(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    argv = ["doctor", "--fix", "--runs-dir", str(store.root)]
    with patch(
        "top_down_planning.cli.doctor.cleanup_staging_dirs",
        side_effect=OSError("cleanup denied"),
    ):
        _assert_operational_both(argv)


def test_attach_save_oserror_is_operational(tmp_path: Path) -> None:
    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
    from tests.helpers import accept_child_run

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
    with patch.object(FileRunStore, "commit", side_effect=OSError("disk full")):
        _assert_operational_both(argv)


def _execute_and_attach_package_error(tmp_path: Path, mutate_package) -> None:
    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    mutate_package(package)
    exec_argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    structured = run_cli([*exec_argv, "--stream-json"])
    human = run_cli(exec_argv)
    assert structured.exit_code == 1
    assert human.exit_code == 1
    assert json.loads(structured.stdout)["ok"] is False
    assert "Traceback" not in structured.stderr
    assert "Traceback" not in human.stderr
    execute_code = json.loads(structured.stdout)["error"]["code"]
    assert execute_code.startswith("package_")

    dummy_child = _create_planning_run(store, "run-20260101T111301-111301")
    attach_argv = [
        "sub-tdp",
        "attach",
        "--parent",
        parent_id,
        "--child",
        dummy_child,
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    attach_structured = run_cli([*attach_argv, "--stream-json"])
    attach_human = run_cli(attach_argv)
    assert attach_structured.exit_code == 1
    assert attach_human.exit_code == 1
    assert json.loads(attach_structured.stdout)["error"]["code"] == "sub_tdp_attach_rejected"
    assert "Traceback" not in attach_structured.stderr
    assert "Traceback" not in attach_human.stderr


def test_package_invalid_utf8_is_package_error(tmp_path: Path) -> None:
    def mutate(package) -> None:
        package.manifest_path.write_bytes(b"\xff\xfe")

    _execute_and_attach_package_error(tmp_path, mutate)


def test_package_unreadable_json_is_package_error(tmp_path: Path) -> None:
    def mutate(package) -> None:
        package.manifest_path.write_text("{not-json", encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate)


def test_package_nonnumeric_schema_version_is_package_error(tmp_path: Path) -> None:
    def mutate(package) -> None:
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = "x"
        package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate)


def test_package_nonnumeric_ordinal_is_package_error(tmp_path: Path) -> None:
    def mutate(package) -> None:
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
        manifest["units"][0]["ordinal"] = "x"
        package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate)


def test_package_nonnumeric_review_revision_is_package_error(tmp_path: Path) -> None:
    def mutate(package) -> None:
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
        approval = manifest["planning_run"]["inherited_plan_approval"]
        approval["target_revision"] = "x"
        package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate)


def test_package_invalid_snapshot_binding_is_package_error(tmp_path: Path) -> None:
    def mutate(package) -> None:
        binding_path = (
            package.manifest_path.parent / "execution" / "context_snapshot_binding.json"
        )
        binding_path.write_text(
            json.dumps({"resource_digests": {"./foo": "a" * 64}}),
            encoding="utf-8",
        )

    _execute_and_attach_package_error(tmp_path, mutate)


def test_self_consistent_schema_invalid_package_config_is_package_error(
    tmp_path: Path,
) -> None:
    _, _, package = _built_package(tmp_path)
    _tamper_embedded_config(
        package, lambda cfg: cfg["planning"].__setitem__("max_depth", "bad")
    )
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    _assert_both_modes(argv, code="package_config_invalid", exit_code=1)


def test_workspace_doctor_reports_symlink_and_canonical_artifact_corruption(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    healthy = _create_planning_run(store, "run-20260101T111401-111401")

    symlink_dir_id = "run-20260101T111402-111402"
    (store.root / symlink_dir_id).symlink_to(store.run_dir(healthy))

    symlink_json_id = _create_planning_run(store, "run-20260101T111403-111403")
    run_json = store.run_dir(symlink_json_id) / "run.json"
    target = store.run_dir(symlink_json_id) / "run.json.real"
    run_json.rename(target)
    run_json.symlink_to(target)

    corrupt_plan_id = _create_planning_run(store, "run-20260101T111404-111404")
    (store.run_dir(corrupt_plan_id) / "plan.json").write_text("{not-json", encoding="utf-8")
    _wipe_txn_dirs(store.run_dir(corrupt_plan_id))

    corrupt_prod_id = _create_planning_run(store, "run-20260101T111405-111405")
    (store.run_dir(corrupt_prod_id) / "production.json").write_text(
        '{"revision": "bad"}',
        encoding="utf-8",
    )
    _wipe_txn_dirs(store.run_dir(corrupt_prod_id))

    corrupt_cfg_id = _create_planning_run(store, "run-20260101T111406-111406")
    _rewrite_resolved_config_yaml(
        store.run_dir(corrupt_cfg_id),
        lambda cfg: cfg["planning"].__setitem__("max_depth", "bad"),
    )

    structured = run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"])
    human = run_cli(["doctor", "--runs-dir", str(store.root)])
    assert structured.exit_code == 1
    payload = json.loads(structured.stdout)
    corrupt = payload["workspace"]["corrupt_run_dirs"]
    assert symlink_dir_id in corrupt
    assert symlink_json_id in corrupt
    assert corrupt_plan_id in corrupt
    assert corrupt_prod_id in corrupt
    assert corrupt_cfg_id in corrupt
    assert healthy not in corrupt
    assert human.exit_code == 1
    assert "Traceback" not in human.stderr

    for run_id in (
        symlink_dir_id,
        symlink_json_id,
        corrupt_plan_id,
        corrupt_prod_id,
        corrupt_cfg_id,
    ):
        _assert_corrupt_both(["doctor", "--run", run_id, "--runs-dir", str(store.root)])
