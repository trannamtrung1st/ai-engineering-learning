"""Slice 7 re-review: operational I/O, persisted config, package, and doctor artifacts."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import dump_yaml, load_yaml
from top_down_planning.config import resolve_config
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.package.digests import compute_package_digest
from top_down_planning.persistence import FileRunStore, PersistenceError
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)
from tests.conftest import run_cli
from tests.fixtures.commit_concurrency_worker import pause_after_run_json_replace_worker
from tests.helpers import create_run_kwargs, minimal_resolved_config, write_config
from tests.support.cli_fakes import (
    _assert_operational_error,
    _engine_patches,
    _minimal_run_yaml,
    _patch_prepare_plan_validated,
)
from tests.support.persistence import (
    _crash_after_dest_replace_count,
    _crash_before_appending_events,
    _crash_before_dest_replace_count,
    _crash_on_appending_events_journal_write,
    _multi_file_commit,
)
from tests.support.run_builders import (
    _built_package,
    _create_planning_run,
    _parent_with_orchestration,
    _pause_run,
    _wipe_txn_dirs,
)


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

    with ExitStack() as stack:
        stack.enter_context(patch.object(FileRunStore, "create_run", _create))
        stack.enter_context(
            patch.object(FileRunStore, "append_event", side_effect=OSError("journal full"))
        )
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ]
    assert leftover
    assert created["n"] >= 1
    assert structured.exit_code == 0
    assert human.exit_code == 0
    payload = json.loads(structured.stdout)
    assert payload.get("error", {}).get("code") != "operational_error"
    assert payload.get("ok") is True or payload.get("run_id")


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
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(FileRunStore, "append_event", side_effect=OSError("journal full"))
        )
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        stack.enter_context(_patch_prepare_plan_validated())
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ]
    assert leftover
    assert structured.exit_code == 0
    assert human.exit_code == 0
    payload = json.loads(structured.stdout)
    assert payload.get("error", {}).get("code") != "operational_error"
    assert payload.get("ok") is True or payload.get("planning_run_id")


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
    with patch.object(FileRunStore, "save_run", side_effect=OSError("disk full")):
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
    from dataclasses import replace

    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    binding = store.load_run(parent_id).get("package_binding") or {}
    bound_manifest = Path(str(binding.get("manifest_path") or package.manifest_path))
    package = replace(package, manifest_path=bound_manifest)
    mutate_package(package)
    exec_argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "execute-runs"),
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
    attach_message = json.loads(attach_structured.stdout)["error"]["message"]
    assert "child run must" not in attach_message
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.__setitem__("schema_version", "1"),
        lambda manifest: manifest.__setitem__("schema_version", 1.5),
        lambda manifest: manifest["units"][0].__setitem__(
            "ordinal", str(manifest["units"][0]["ordinal"])
        ),
        lambda manifest: manifest["units"][0].__setitem__(
            "ordinal", float(manifest["units"][0]["ordinal"]) + 0.5
        ),
        lambda manifest: manifest["planning_run"].__setitem__(
            "approved_plan_revision",
            str(manifest["planning_run"]["approved_plan_revision"]),
        ),
        lambda manifest: manifest["planning_run"].__setitem__(
            "approved_plan_revision",
            float(manifest["planning_run"]["approved_plan_revision"]) + 0.5,
        ),
        lambda manifest: manifest["planning_run"]["inherited_plan_approval"].__setitem__(
            "target_revision",
            str(manifest["planning_run"]["inherited_plan_approval"]["target_revision"]),
        ),
        lambda manifest: manifest["planning_run"]["inherited_plan_approval"].__setitem__(
            "target_revision",
            float(manifest["planning_run"]["inherited_plan_approval"]["target_revision"])
            + 0.5,
        ),
    ],
)
def test_package_coercible_integers_are_rejected(tmp_path: Path, mutate) -> None:
    from top_down_planning.package.builder import digest_review_record

    def mutate_package(package) -> None:
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
        mutate(manifest)
        attestation = manifest["planning_run"]["inherited_plan_approval"]
        approval_path = (
            package.manifest_path.parent / "parent" / "inherited_plan_approval.json"
        )
        approval_path.write_text(json.dumps(attestation), encoding="utf-8")
        manifest["planning_run"]["whole_plan_review_digest"] = digest_review_record(
            attestation
        )
        _recompute_package_digest(manifest)
        package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate_package)


def test_structurally_valid_snapshot_binding_digest_mismatch_is_package_error(
    tmp_path: Path,
) -> None:
    def mutate(package) -> None:
        binding_path = (
            package.manifest_path.parent / "execution" / "context_snapshot_binding.json"
        )
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        resources = binding.setdefault("resource_digests", {})
        if resources:
            first_path = next(iter(resources))
            current = resources[first_path]
            resources[first_path] = "b" * 64 if current != "b" * 64 else "c" * 64
        else:
            resources["extra.md"] = "a" * 64
        binding_path.write_text(json.dumps(binding), encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate)


def _assert_doctor_marks_corrupt(store: FileRunStore, run_id: str) -> None:
    structured = run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"])
    assert structured.exit_code == 1
    assert run_id in json.loads(structured.stdout)["workspace"]["corrupt_run_dirs"]
    _assert_corrupt_both(["doctor", "--run", run_id, "--runs-dir", str(store.root)])


def test_doctor_reports_valid_but_digest_inconsistent_snapshots(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")

    plan_id = _create_planning_run(store, "run-20260101T111501-111501")
    plan_path = store.run_dir(plan_id) / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["output_goal"] = "A different but valid goal."
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    _wipe_txn_dirs(store.run_dir(plan_id))
    _assert_doctor_marks_corrupt(store, plan_id)

    cfg_id = _create_planning_run(store, "run-20260101T111502-111502")
    _rewrite_resolved_config_yaml(
        store.run_dir(cfg_id),
        lambda cfg: cfg["planning"].__setitem__("max_depth", 9),
    )
    _assert_doctor_marks_corrupt(store, cfg_id)

    binding_id = _create_planning_run(store, "run-20260101T111503-111503")
    run_path = store.run_dir(binding_id) / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    resources = run["context_snapshot_binding"].setdefault("resource_digests", {})
    if resources:
        first_path = next(iter(resources))
        current = resources[first_path]
        resources[first_path] = "b" * 64 if current != "b" * 64 else "c" * 64
    else:
        resources["extra.md"] = "a" * 64
    run_path.write_text(json.dumps(run), encoding="utf-8")
    _wipe_txn_dirs(store.run_dir(binding_id))
    _assert_doctor_marks_corrupt(store, binding_id)

    output_id = _create_planning_run(store, "run-20260101T111504-111504")
    run_path = store.run_dir(output_id) / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["digests"]["output"] = "b" * 64
    run_path.write_text(json.dumps(run), encoding="utf-8")
    _wipe_txn_dirs(store.run_dir(output_id))
    _assert_doctor_marks_corrupt(store, output_id)

    review_id = _create_planning_run(store, "run-20260101T111505-111505")
    reviews_dir = store.run_dir(review_id) / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    (reviews_dir / "review-corrupt-01.json").write_text(
        json.dumps({"id": "review-corrupt-01", "status": "not-a-status"}),
        encoding="utf-8",
    )
    _wipe_txn_dirs(store.run_dir(review_id))
    _assert_doctor_marks_corrupt(store, review_id)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.__setitem__("workspace", 1),
        lambda manifest: manifest.__setitem__("parent", True),
        lambda manifest: manifest.__setitem__("units", 7),
        lambda manifest: manifest["units"][0].__setitem__("assigned_item_ids", 3),
        lambda manifest: manifest["units"][0].__setitem__("depends_on", 3),
        lambda manifest: manifest["units"][0].__setitem__(
            "external_prerequisites", 3
        ),
        lambda manifest: manifest["units"][0].__setitem__(
            "required_upstream_outputs", 3
        ),
    ],
)
def test_package_wrong_container_types_are_package_errors(
    tmp_path: Path, mutate
) -> None:
    def mutate_package(package) -> None:
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
        mutate(manifest)
        package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    _execute_and_attach_package_error(tmp_path, mutate_package)


def _create_workspace_backed_planning_run(tmp_path: Path, run_id: str) -> FileRunStore:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "input.md").write_text("original input\n", encoding="utf-8")
    (workspace / "goal.md").write_text("Ship the product.\n", encoding="utf-8")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "ok.md").write_text("ok\n", encoding="utf-8")
    config = minimal_resolved_config()
    config["run"]["input_refs"] = ["input.md"]
    config["run"].pop("output_goal", None)
    config["run"]["output_goal_file"] = "goal.md"
    config["agent_context"]["roles"]["producer"]["resources"] = ["docs/*.md"]
    store = FileRunStore(tmp_path / "runs")
    store.create_run(
        run_id,
        plan=Plan(
            id="plan-workspace",
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
        **create_run_kwargs(workspace, resolved_config=config),
    )
    return store


def _assert_doctor_run_healthy(store: FileRunStore, run_id: str) -> None:
    structured = run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"])
    payload = json.loads(structured.stdout)
    assert run_id not in payload["workspace"]["corrupt_run_dirs"]
    targeted = run_cli(
        ["doctor", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    assert targeted.exit_code == 0
    assert json.loads(targeted.stdout).get("ok") is True
    assert "Traceback" not in structured.stderr
    assert "Traceback" not in targeted.stderr


def test_doctor_does_not_treat_live_workspace_drift_as_corrupt_run(
    tmp_path: Path,
) -> None:
    run_id = "run-20260101T111601-111601"
    store = _create_workspace_backed_planning_run(tmp_path, run_id)
    workspace = tmp_path / "ws"
    _assert_doctor_run_healthy(store, run_id)

    (workspace / "input.md").write_text("changed input\n", encoding="utf-8")
    _assert_doctor_run_healthy(store, run_id)

    (workspace / "goal.md").write_text("A different goal.\n", encoding="utf-8")
    _assert_doctor_run_healthy(store, run_id)

    (workspace / "docs" / "ok.md").unlink()
    _assert_doctor_run_healthy(store, run_id)

    shutil.rmtree(workspace)
    _assert_doctor_run_healthy(store, run_id)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.pop("workspace", None),
        lambda manifest: manifest["workspace"].pop("path", None),
        lambda manifest: manifest["workspace"].__setitem__("path", ""),
        lambda manifest: manifest["workspace"].__setitem__("path", "   "),
        lambda manifest: manifest["workspace"].__setitem__("portability", "portable"),
        lambda manifest: manifest["workspace"].__setitem__("portability", 1),
    ],
)
def test_package_workspace_binding_is_required_and_not_cwd(
    tmp_path: Path, mutate
) -> None:
    def mutate_package(package) -> None:
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
        mutate(manifest)
        _recompute_package_digest(manifest)
        package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        _execute_and_attach_package_error(tmp_path, mutate_package)
    finally:
        os.chdir(previous)


@pytest.mark.parametrize(
    "mutate_run_dir",
    [
        lambda run_dir: (run_dir / "events.jsonl").unlink(),
        lambda run_dir: (run_dir / "events.jsonl").write_text(
            "{not-json\n", encoding="utf-8"
        ),
        lambda run_dir: (run_dir / "events.jsonl").write_text("", encoding="utf-8"),
        lambda run_dir: (run_dir / "events.jsonl").write_text(
            json.dumps({"type": "run_updated", "run_id": run_dir.name}) + "\n",
            encoding="utf-8",
        ),
        lambda run_dir: (run_dir / "events.jsonl").write_text(
            json.dumps(
                {
                    "type": "run_created",
                    "run_id": "run-20260101T111999-111999",
                    "revision": 0,
                    "phase": "planning",
                    "ts": "2026-01-01T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        ),
        lambda run_dir: (run_dir / "invocation.json").unlink(),
        lambda run_dir: (run_dir / "invocation.json").write_text(
            "{not-json", encoding="utf-8"
        ),
        lambda run_dir: (run_dir / "invocation.json").write_text(
            "[]", encoding="utf-8"
        ),
    ],
)
def test_doctor_reports_missing_or_corrupt_events_and_invocation(
    tmp_path: Path, mutate_run_dir
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111701-111701"
    _create_planning_run(store, run_id)
    mutate_run_dir(store.run_dir(run_id))
    _wipe_txn_dirs(store.run_dir(run_id))
    _assert_doctor_marks_corrupt(store, run_id)


def _assert_doctor_not_corrupt(store: FileRunStore, run_id: str) -> dict:
    structured = run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"])
    workspace = json.loads(structured.stdout)["workspace"]
    assert run_id not in workspace["corrupt_run_dirs"]
    assert "Traceback" not in structured.stderr
    targeted = run_cli(
        ["doctor", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    targeted_payload = json.loads(targeted.stdout)
    assert targeted_payload.get("error", {}).get("code") != "corrupt_run"
    assert "Traceback" not in targeted.stderr
    human = run_cli(["doctor", "--run", run_id, "--runs-dir", str(store.root)])
    assert "Traceback" not in human.stderr
    return {
        "workspace": structured,
        "workspace_payload": json.loads(structured.stdout),
        "targeted": targeted,
        "targeted_payload": targeted_payload,
    }


def _crash_on_replacing_status():
    from core_tools.persistence import atomic_write_json as original_write

    def patched_write(path: Path, payload: dict) -> None:
        if path.name == "journal.json" and payload.get("status") == "replacing":
            raise OSError("simulated crash")
        original_write(path, payload)

    return patched_write


def test_doctor_does_not_treat_in_progress_commit_as_corrupt(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111801-111801"
    _create_planning_run(store, run_id)
    ctx = multiprocessing.get_context("spawn")
    ready_queue: multiprocessing.Queue[str] = ctx.Queue()
    release_queue: multiprocessing.Queue[str] = ctx.Queue()
    writer = ctx.Process(
        target=pause_after_run_json_replace_worker,
        args=(str(store.root), run_id, ready_queue, release_queue),
    )
    writer.start()
    try:
        assert ready_queue.get(timeout=30) == "ready"
        observed = _assert_doctor_not_corrupt(store, run_id)
        workspace = observed["workspace_payload"]["workspace"]
        assert run_id in workspace.get("busy_run_dirs", [])
        assert observed["targeted_payload"].get("busy") is True
        assert observed["targeted"].exit_code == 0
    finally:
        release_queue.put("release")
        writer.join(timeout=30)
        assert writer.exitcode == 0
    _assert_doctor_run_healthy(store, run_id)


@pytest.mark.parametrize(
    "crash",
    [
        lambda: patch(
            "top_down_planning.persistence.file_store.atomic_write_json",
            _crash_on_replacing_status(),
        ),
        lambda: patch.object(Path, "replace", _crash_after_dest_replace_count(1)),
        lambda: patch(
            "top_down_planning.persistence.file_store.atomic_write_json",
            _crash_before_appending_events(),
        ),
        lambda: patch.object(
            FileRunStore,
            "_retire_transaction_dir",
            side_effect=OSError("simulated crash"),
        ),
    ],
)
def test_doctor_reports_recoverable_transactions_and_fix_recovers_them(
    tmp_path: Path, crash
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111802-111802"
    _create_planning_run(store, run_id)
    with crash():
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    assert list(store.run_dir(run_id).glob(".txn-*"))

    observed = _assert_doctor_not_corrupt(store, run_id)
    workspace = observed["workspace_payload"]["workspace"]
    assert run_id in workspace.get("recoverable_transaction_run_ids", [])
    assert list(store.run_dir(run_id).glob(".txn-*"))
    assert observed["targeted_payload"].get("recoverable_transaction") is True
    assert observed["targeted"].exit_code == 0

    fixed = run_cli(
        ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
    )
    assert fixed.exit_code == 0
    assert "Traceback" not in fixed.stderr
    assert run_id not in json.loads(fixed.stdout)["workspace"]["corrupt_run_dirs"]
    assert not list(store.run_dir(run_id).glob(".txn-*"))
    targeted_fix = run_cli(
        [
            "doctor",
            "--fix",
            "--run",
            run_id,
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert targeted_fix.exit_code == 0
    assert json.loads(targeted_fix.stdout).get("error", {}).get("code") != "corrupt_run"
    _assert_doctor_run_healthy(store, run_id)


def test_store_invocation_boundary_uses_persisted_invocation_schema(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111803-111803"
    invalid = create_run_kwargs(store.root)
    invalid["invocation"]["stream_json"] = "yes"
    with pytest.raises(PersistenceError, match="stream_json"):
        store.create_run(
            run_id,
            plan=Plan(
                id="plan-invocation",
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
            **invalid,
        )
    _create_planning_run(store, run_id)
    with pytest.raises(PersistenceError, match="stream_json"):
        store.save_invocation(run_id, {"stream_json": "yes"})
    loaded = store.load_invocation(run_id)
    assert loaded.get("stream_json") is False


_DIGEST = "a" * 64


def _outside_names(path: Path) -> set[str]:
    return {entry.name for entry in path.iterdir()}


def _txn_dir_names(run_dir: Path) -> list[str]:
    return sorted(path.name for path in run_dir.glob(".txn-*"))


def _assert_doctor_rejects_unrecoverable_without_outside_writes(
    store: FileRunStore,
    run_id: str,
    *,
    evidence_dir: Path,
    outside: Path | None = None,
    outside_before: set[str] | None = None,
) -> None:
    _assert_doctor_marks_corrupt(store, run_id)
    workspace = json.loads(
        run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"]).stdout
    )["workspace"]
    assert run_id not in workspace.get("recoverable_transaction_run_ids", [])
    targeted = json.loads(
        run_cli(
            ["doctor", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        ).stdout
    )
    assert targeted.get("recoverable_transaction") is not True

    evidence_before = _txn_dir_names(evidence_dir)
    assert evidence_before

    workspace_fix = run_cli(
        ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
    )
    assert workspace_fix.exit_code == 1
    assert "Traceback" not in workspace_fix.stderr
    workspace_fix_payload = json.loads(workspace_fix.stdout)
    assert run_id in workspace_fix_payload["workspace"]["corrupt_run_dirs"]
    assert run_id not in workspace_fix_payload["workspace"].get(
        "recoverable_transaction_run_ids", []
    )
    assert _txn_dir_names(evidence_dir) == evidence_before

    _assert_corrupt_both(
        ["doctor", "--fix", "--run", run_id, "--runs-dir", str(store.root)]
    )
    assert _txn_dir_names(evidence_dir) == evidence_before

    if outside is not None:
        assert not (outside / ".commit.lock").exists()
        assert _outside_names(outside) == outside_before


def test_doctor_rejects_run_dir_symlink_before_creating_commit_lock(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True)
    outside = tmp_path / "outside-run"
    outside.mkdir()
    (outside / "run.json").write_text("{}", encoding="utf-8")
    run_id = "run-20260101T111901-111901"
    (store.root / run_id).symlink_to(outside)
    outside_before = _outside_names(outside)
    assert ".commit.lock" not in outside_before

    _assert_doctor_marks_corrupt(store, run_id)
    assert not (outside / ".commit.lock").exists()
    assert _outside_names(outside) == outside_before

    workspace_fix = run_cli(
        ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
    )
    assert workspace_fix.exit_code == 1
    assert "Traceback" not in workspace_fix.stderr
    assert run_id in json.loads(workspace_fix.stdout)["workspace"]["corrupt_run_dirs"]
    _assert_corrupt_both(
        ["doctor", "--fix", "--run", run_id, "--runs-dir", str(store.root)]
    )
    assert not (outside / ".commit.lock").exists()
    assert _outside_names(outside) == outside_before


def _prepared_journal(txn_id: str, *, status: str = "prepared") -> dict:
    return {
        "txn_id": txn_id,
        "status": status,
        "files": [
            {
                "kind": "run",
                "name": "run.json",
                "digest": _DIGEST,
                "had_destination": True,
            }
        ],
        "events": [],
        "backups": [],
        "replaced": [],
    }


def _plant_missing_journal(run_dir: Path) -> None:
    (run_dir / ".txn-aaaaaaaaaaaa").mkdir()


def _plant_malformed_journal(run_dir: Path) -> None:
    txn_dir = run_dir / ".txn-bbbbbbbbbbbb"
    txn_dir.mkdir()
    (txn_dir / "journal.json").write_text("{not-json", encoding="utf-8")


def _plant_txn_id_mismatch(run_dir: Path) -> None:
    txn_dir = run_dir / ".txn-cccccccccccc"
    txn_dir.mkdir()
    (txn_dir / "journal.json").write_text(
        json.dumps(_prepared_journal("dddddddddddd")),
        encoding="utf-8",
    )


def _plant_unknown_status(run_dir: Path) -> None:
    txn_dir = run_dir / ".txn-eeeeeeeeeeee"
    txn_dir.mkdir()
    (txn_dir / "journal.json").write_text(
        json.dumps(_prepared_journal("eeeeeeeeeeee", status="not-a-status")),
        encoding="utf-8",
    )


def _plant_two_txn_dirs(run_dir: Path) -> None:
    (run_dir / ".txn-ffffffff0001").mkdir()
    (run_dir / ".txn-ffffffff0002").mkdir()


def _plant_symlinked_txn(run_dir: Path, outside: Path) -> None:
    target = outside / "txn-target"
    target.mkdir()
    (run_dir / ".txn-ffffffffffff").symlink_to(target)


def _plant_missing_backup(run_dir: Path) -> None:
    txn_id = "111111111111"
    txn_dir = run_dir / f".txn-{txn_id}"
    txn_dir.mkdir()
    payload = {
        "txn_id": txn_id,
        "status": "replacing",
        "files": [
            {
                "kind": "run",
                "name": "run.json",
                "digest": _DIGEST,
                "had_destination": True,
            }
        ],
        "events": [],
        "backups": ["run.json"],
        "replaced": [],
    }
    (txn_dir / "journal.json").write_text(json.dumps(payload), encoding="utf-8")


def _plant_missing_staged_file(run_dir: Path) -> None:
    txn_id = "222222222222"
    txn_dir = run_dir / f".txn-{txn_id}"
    txn_dir.mkdir()
    (txn_dir / "journal.json").write_text(
        json.dumps(_prepared_journal(txn_id)),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "plant",
    [
        _plant_missing_journal,
        _plant_malformed_journal,
        _plant_txn_id_mismatch,
        _plant_unknown_status,
        _plant_two_txn_dirs,
        _plant_missing_backup,
        _plant_missing_staged_file,
    ],
)
def test_doctor_does_not_advertise_malformed_transactions_as_recoverable(
    tmp_path: Path, plant
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111902-111902"
    _create_planning_run(store, run_id)
    run_dir = store.run_dir(run_id)
    _wipe_txn_dirs(run_dir)
    plant(run_dir)
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def test_doctor_treats_symlinked_transaction_dir_as_unrecoverable(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111903-111903"
    _create_planning_run(store, run_id)
    run_dir = store.run_dir(run_id)
    _wipe_txn_dirs(run_dir)
    outside = tmp_path / "outside-txn"
    outside.mkdir()
    _plant_symlinked_txn(run_dir, outside)
    outside_before = _outside_names(outside)
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
        outside=outside,
        outside_before=outside_before,
    )


def _crash_after_committed_before_retire():
    return patch.object(
        FileRunStore,
        "_retire_transaction_dir",
        side_effect=OSError("simulated crash"),
    )


def _tamper_replaced_plan(run_dir: Path) -> None:
    plan_path = run_dir / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["output_goal"] = "Tampered destination that recovery cannot republish."
    plan_path.write_text(json.dumps(plan), encoding="utf-8")


def _tamper_events_prefix(run_dir: Path) -> None:
    events_path = run_dir / "events.jsonl"
    data = events_path.read_bytes()
    events_path.write_bytes(b"x" + data[1:] if data else b"x")


@pytest.mark.parametrize(
    "crash",
    [
        lambda: patch(
            "top_down_planning.persistence.file_store.atomic_write_json",
            _crash_before_appending_events(),
        ),
        _crash_after_committed_before_retire,
    ],
)
@pytest.mark.parametrize("tamper", [_tamper_replaced_plan, _tamper_events_prefix])
def test_doctor_does_not_advertise_unrecoverable_committed_disk_state(
    tmp_path: Path, crash, tamper
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111904-111904"
    _create_planning_run(store, run_id)
    with crash():
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    assert list(run_dir.glob(".txn-*"))
    tamper(run_dir)
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def _leave_prepared_transaction(store: FileRunStore, run_id: str) -> Path:
    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_on_replacing_status(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    assert list(run_dir.glob(".txn-*"))
    return run_dir


def test_doctor_reports_prepared_transaction_when_canonical_artifacts_are_healthy(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111905-111905"
    _create_planning_run(store, run_id)
    _leave_prepared_transaction(store, run_id)
    observed = _assert_doctor_not_corrupt(store, run_id)
    workspace = observed["workspace_payload"]["workspace"]
    assert run_id in workspace.get("recoverable_transaction_run_ids", [])
    assert observed["targeted_payload"].get("recoverable_transaction") is True
    assert observed["targeted"].exit_code == 0


def _corrupt_resolved_config_in_place(run_dir: Path) -> None:
    path = run_dir / "resolved-config.yaml"
    payload = load_yaml(path.read_text(encoding="utf-8"))
    payload["planning"]["max_depth"] = "bad"
    path.write_text(dump_yaml(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "mutate_run_dir",
    [
        lambda run_dir: (run_dir / "plan.json").write_text("{not-json", encoding="utf-8"),
        lambda run_dir: (run_dir / "invocation.json").write_text("[]", encoding="utf-8"),
        lambda run_dir: (run_dir / "events.jsonl").write_text("{not-json\n", encoding="utf-8"),
        _corrupt_resolved_config_in_place,
    ],
)
def test_doctor_does_not_hide_canonical_corruption_behind_prepared_transaction(
    tmp_path: Path, mutate_run_dir
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111906-111906"
    _create_planning_run(store, run_id)
    run_dir = _leave_prepared_transaction(store, run_id)
    mutate_run_dir(run_dir)
    observed_workspace = json.loads(
        run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"]).stdout
    )["workspace"]
    assert run_id not in observed_workspace.get("recoverable_transaction_run_ids", [])
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def _leave_fully_replaced_replacing_transaction(store: FileRunStore, run_id: str) -> Path:
    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_on_appending_events_journal_write(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    txn_dirs = list(run_dir.glob(".txn-*"))
    assert txn_dirs
    journal = json.loads((txn_dirs[0] / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "replacing"
    replaced = list(journal["replaced"])
    staged_names = [entry["name"] for entry in journal["files"]]
    assert replaced == staged_names
    assert staged_names
    return run_dir


def test_doctor_does_not_advertise_unrecoverable_fully_replaced_replacing_events(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111907-111907"
    _create_planning_run(store, run_id)
    run_dir = _leave_fully_replaced_replacing_transaction(store, run_id)
    _tamper_events_prefix(run_dir)
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def _corrupt_invocation(run_dir: Path) -> None:
    (run_dir / "invocation.json").write_text("[]", encoding="utf-8")


def _in_flight_transaction_crashes():
    return [
        (
            "replacing",
            lambda: patch(
                "top_down_planning.persistence.file_store.atomic_write_json",
                _crash_on_appending_events_journal_write(),
            ),
        ),
        (
            "appending_events",
            lambda: patch(
                "top_down_planning.persistence.file_store.atomic_write_json",
                _crash_before_appending_events(),
            ),
        ),
        ("committed", _crash_after_committed_before_retire),
    ]


@pytest.mark.parametrize("status, crash", _in_flight_transaction_crashes())
def test_doctor_reports_in_flight_transaction_when_unaffected_artifacts_are_healthy(
    tmp_path: Path, status, crash
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111908-111908"
    _create_planning_run(store, run_id)
    with crash():
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    journal = json.loads(
        next(run_dir.glob(".txn-*")).joinpath("journal.json").read_text(encoding="utf-8")
    )
    assert journal["status"] == status
    observed = _assert_doctor_not_corrupt(store, run_id)
    workspace = observed["workspace_payload"]["workspace"]
    assert run_id in workspace.get("recoverable_transaction_run_ids", [])
    assert observed["targeted_payload"].get("recoverable_transaction") is True
    assert observed["targeted"].exit_code == 0


@pytest.mark.parametrize("status, crash", _in_flight_transaction_crashes())
def test_doctor_does_not_hide_unrelated_corruption_behind_in_flight_transaction(
    tmp_path: Path, status, crash
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111909-111909"
    _create_planning_run(store, run_id)
    with crash():
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    journal = json.loads(
        next(run_dir.glob(".txn-*")).joinpath("journal.json").read_text(encoding="utf-8")
    )
    assert journal["status"] == status
    assert "invocation.json" not in [entry["name"] for entry in journal["files"]]
    _corrupt_invocation(run_dir)
    observed_workspace = json.loads(
        run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"]).stdout
    )["workspace"]
    assert run_id not in observed_workspace.get("recoverable_transaction_run_ids", [])
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def _mutate_unbound_config_max_depth(run_dir: Path) -> None:
    path = run_dir / "resolved-config.yaml"
    payload = load_yaml(path.read_text(encoding="utf-8"))
    current = payload["planning"]["max_depth"]
    payload["planning"]["max_depth"] = 9 if current != 9 else 3
    path.write_text(dump_yaml(payload), encoding="utf-8")


@pytest.mark.parametrize("status, crash", _in_flight_transaction_crashes())
def test_doctor_does_not_hide_unbound_config_digest_behind_in_flight_transaction(
    tmp_path: Path, status, crash
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111910-111910"
    _create_planning_run(store, run_id)
    with crash():
        with pytest.raises(OSError, match="simulated crash"):
            _multi_file_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    journal = json.loads(
        next(run_dir.glob(".txn-*")).joinpath("journal.json").read_text(encoding="utf-8")
    )
    assert journal["status"] == status
    staged_names = [entry["name"] for entry in journal["files"]]
    assert "run.json" in staged_names
    assert "plan.json" in staged_names
    assert "resolved-config.yaml" not in staged_names
    _mutate_unbound_config_max_depth(run_dir)
    observed_workspace = json.loads(
        run_cli(["doctor", "--runs-dir", str(store.root), "--stream-json"]).stdout
    )["workspace"]
    assert run_id not in observed_workspace.get("recoverable_transaction_run_ids", [])
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def _run_plan_invocation_commit(store: FileRunStore, run_id: str) -> None:
    from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_plan_update

    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    invocation = dict(store.load_invocation(run_id))
    run_expected = int(run["revision"])
    plan_expected = int(plan["revision"])
    plan = dict(plan)
    plan["revision"] = plan_expected + 1
    run = bind_run_digests_for_plan_update(
        {**dict(run), "revision": run_expected + 1},
        plan,
    )
    invocation["stream_json"] = not bool(invocation.get("stream_json"))
    store.commit(
        run_id,
        CommitSpec(
            run=run,
            run_expected_revision=run_expected,
            plan=plan,
            plan_expected_revision=plan_expected,
            invocation=invocation,
            events=[{"type": "test_commit", "run_id": run_id}],
        ),
    )


def _leave_partial_replacing_run_plan_before_invocation(
    store: FileRunStore, run_id: str
) -> Path:
    with patch.object(Path, "replace", _crash_before_dest_replace_count(3)):
        with pytest.raises(OSError, match="simulated crash"):
            _run_plan_invocation_commit(store, run_id)
    run_dir = store.run_dir(run_id)
    txn_dirs = list(run_dir.glob(".txn-*"))
    assert txn_dirs
    journal = json.loads((txn_dirs[0] / "journal.json").read_text(encoding="utf-8"))
    assert journal["status"] == "replacing"
    staged_names = [entry["name"] for entry in journal["files"]]
    assert staged_names == ["run.json", "plan.json", "invocation.json"]
    assert journal["replaced"] == ["run.json", "plan.json"]
    return run_dir


def test_doctor_treats_rollback_txn_as_recoverable_when_in_flight_plan_is_malformed(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111911-111911"
    _create_planning_run(store, run_id)
    prior_plan = json.loads(
        (store.run_dir(run_id) / "plan.json").read_text(encoding="utf-8")
    )
    run_dir = _leave_partial_replacing_run_plan_before_invocation(store, run_id)
    (run_dir / "plan.json").write_text("{not-json", encoding="utf-8")

    clone_root = tmp_path / "clone-runs"
    shutil.copytree(store.root, clone_root)
    clone_store = FileRunStore(clone_root)
    clone_store.recover_incomplete_transactions(run_id)
    clone_dir = clone_store.run_dir(run_id)
    restored = json.loads((clone_dir / "plan.json").read_text(encoding="utf-8"))
    assert restored == prior_plan
    assert not list(clone_dir.glob(".txn-*"))

    observed = _assert_doctor_not_corrupt(store, run_id)
    workspace = observed["workspace_payload"]["workspace"]
    assert run_id in workspace.get("recoverable_transaction_run_ids", [])
    assert observed["targeted_payload"].get("recoverable_transaction") is True
    assert observed["targeted"].exit_code == 0
    assert list(run_dir.glob(".txn-*"))

    fixed = run_cli(
        ["doctor", "--fix", "--runs-dir", str(store.root), "--stream-json"]
    )
    assert fixed.exit_code == 0
    assert "Traceback" not in fixed.stderr
    assert run_id not in json.loads(fixed.stdout)["workspace"]["corrupt_run_dirs"]
    assert not list(run_dir.glob(".txn-*"))
    targeted_fix = run_cli(
        [
            "doctor",
            "--fix",
            "--run",
            run_id,
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert targeted_fix.exit_code == 0
    assert json.loads(targeted_fix.stdout).get("error", {}).get("code") != "corrupt_run"
    _assert_doctor_run_healthy(store, run_id)
    assert json.loads((run_dir / "plan.json").read_text(encoding="utf-8")) == prior_plan


def _rewrite_json_file_as_utf16(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_bytes(json.dumps(payload).encode("utf-16"))


def _plant_valid_review(run_dir: Path) -> Path:
    from top_down_planning.domain.reviews import ReviewLoop

    review_id = "review-utf16-01"
    payload = ReviewLoop(
        id=review_id,
        type="focused_plan",
        target_revision=0,
        scope={"kind": "plan_item", "item_id": "item-root"},
        status="pending",
        revise_at="blocker",
    ).to_dict()
    reviews_dir = run_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    path = reviews_dir / f"{review_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "relative",
    ["run.json", "plan.json", "production.json", "invocation.json"],
)
def test_doctor_reports_utf16_canonical_json_as_corrupt(
    tmp_path: Path, relative: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111912-111912"
    _create_planning_run(store, run_id)
    run_dir = store.run_dir(run_id)
    _wipe_txn_dirs(run_dir)
    _rewrite_json_file_as_utf16(run_dir / relative)
    _assert_doctor_marks_corrupt(store, run_id)


def test_doctor_reports_utf16_review_record_as_corrupt(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111913-111913"
    _create_planning_run(store, run_id)
    run_dir = store.run_dir(run_id)
    review_path = _plant_valid_review(run_dir)
    _wipe_txn_dirs(run_dir)
    _assert_doctor_run_healthy(store, run_id)
    _rewrite_json_file_as_utf16(review_path)
    _assert_doctor_marks_corrupt(store, run_id)


def test_doctor_does_not_accept_utf16_json_behind_pending_transaction(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111914-111914"
    _create_planning_run(store, run_id)
    run_dir = _leave_prepared_transaction(store, run_id)
    _rewrite_json_file_as_utf16(run_dir / "invocation.json")
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )


def test_doctor_does_not_accept_utf16_review_behind_pending_transaction(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T111915-111915"
    _create_planning_run(store, run_id)
    review_path = _plant_valid_review(store.run_dir(run_id))
    run_dir = _leave_prepared_transaction(store, run_id)
    _rewrite_json_file_as_utf16(review_path)
    _assert_doctor_rejects_unrecoverable_without_outside_writes(
        store,
        run_id,
        evidence_dir=run_dir,
    )

