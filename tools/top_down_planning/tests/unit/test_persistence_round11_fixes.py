"""Regression tests for Slice 3 round-11 review (TDP-PERSIST-039..043)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError, TransactionRecoveryError, atomic_write_json
from top_down_planning.config.context import compute_context_snapshot_digest_from_payload
from top_down_planning.config.context_digests import validate_resume_context_bindings
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import create_run_kwargs, minimal_resolved_config, whole_plan_approval_record
from tests.support.persistence import _create_run


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0021{suffix}-0021{suffix}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_recovery_rejects_journal_symlink(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = _new_run_id("05")
    run_b = _new_run_id("06")
    _create_run(store, run_a)
    _create_run(store, run_b)
    run_a_before = (store.run_dir(run_a) / "run.json").read_bytes()

    txn_id = "evil-journal"
    txn_dir = store.run_dir(run_a) / f".txn-{txn_id}"
    txn_dir.mkdir()
    journal_link = txn_dir / "journal.json"
    journal_link.symlink_to(store.run_dir(run_b) / "run.json")

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        FileRunStore(tmp_path).load_run(run_a)

    assert (store.run_dir(run_a) / "run.json").read_bytes() == run_a_before
    assert list(store.run_dir(run_a).glob(".txn-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_recovery_rejects_backups_directory_symlink(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = _new_run_id("01")
    run_b = _new_run_id("02")
    _create_run(store, run_a)
    _create_run(store, run_b)
    run_a_before = (store.run_dir(run_a) / "run.json").read_bytes()
    run_b_before = (store.run_dir(run_b) / "run.json").read_bytes()

    txn_id = "evil-backups"
    txn_dir = store.run_dir(run_a) / f".txn-{txn_id}"
    txn_dir.mkdir()
    backups_link = txn_dir / "backups"
    backups_link.symlink_to(store.run_dir(run_b), target_is_directory=True)
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "replacing",
            "files": [
                {
                    "kind": "run",
                    "name": "run.json",
                    "digest": "0" * 64,
                    "had_destination": True,
                }
            ],
            "events": [],
            "backups": ["run.json"],
            "replaced": [],
        },
    )

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        FileRunStore(tmp_path).load_run(run_a)

    assert (store.run_dir(run_a) / "run.json").read_bytes() == run_a_before
    assert (store.run_dir(run_b) / "run.json").read_bytes() == run_b_before
    assert list(store.run_dir(run_a).glob(".txn-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_recovery_rejects_backup_file_symlink(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = _new_run_id("11")
    run_b = _new_run_id("12")
    _create_run(store, run_a)
    _create_run(store, run_b)
    run_a_before = (store.run_dir(run_a) / "run.json").read_bytes()

    txn_id = "evil-backup-file"
    txn_dir = store.run_dir(run_a) / f".txn-{txn_id}"
    txn_dir.mkdir()
    (txn_dir / "backups").mkdir()
    backup_link = txn_dir / "backups" / "run.json"
    backup_link.symlink_to(store.run_dir(run_b) / "run.json")
    atomic_write_json(
        txn_dir / "journal.json",
        {
            "txn_id": txn_id,
            "status": "replacing",
            "files": [
                {
                    "kind": "run",
                    "name": "run.json",
                    "digest": "0" * 64,
                    "had_destination": True,
                }
            ],
            "events": [],
            "backups": ["run.json"],
            "replaced": [],
        },
    )

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        FileRunStore(tmp_path).load_run(run_a)

    assert (store.run_dir(run_a) / "run.json").read_bytes() == run_a_before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_list_reviews_rejects_symlinked_record(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = _new_run_id("21")
    run_b = _new_run_id("22")
    _create_run(store, run_a)
    _create_run(store, run_b)
    approval = whole_plan_approval_record(store, run_b)
    atomic_write_json(store.reviews_dir(run_b) / f"{approval['id']}.json", approval)
    review_link = store.reviews_dir(run_a) / f"{approval['id']}.json"
    review_link.symlink_to(store.reviews_dir(run_b) / f"{approval['id']}.json")

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        store.list_reviews(run_a)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink checks")
def test_list_capabilities_rejects_symlinked_record(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_a = _new_run_id("31")
    run_b = _new_run_id("32")
    _create_run(store, run_a)
    _create_run(store, run_b)
    _, record, _ = store.create_capability(
        run_b,
        role="producer",
        phase="production",
        allowed_ops=frozenset({"apply"}),
        session_id="sess-b",
    )
    capability_link = store.capabilities_dir(run_a) / f"{record['id']}.json"
    store.capabilities_dir(run_a).mkdir(parents=True, exist_ok=True)
    capability_link.symlink_to(store.capabilities_dir(run_b) / f"{record['id']}.json")

    with pytest.raises(PersistenceError, match="must not be a symlink"):
        store.list_capabilities(run_a)


def test_save_run_rejects_forged_context_snapshot_binding(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("41")
    _create_run(store, run_id)
    before = (store.run_dir(run_id) / "run.json").read_bytes()
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    forged_binding = {
        "resource_digests": {},
        "skill_digests": {},
        "guidance_digests": [],
    }
    run["context_snapshot_binding"] = forged_binding
    digests = dict(run.get("digests") or {})
    digests["context_snapshot"] = compute_context_snapshot_digest_from_payload(forged_binding)
    run["digests"] = digests

    with pytest.raises(PersistenceError, match="context_snapshot_binding transition"):
        store.save_run(run_id, run, expected)

    assert (store.run_dir(run_id) / "run.json").read_bytes() == before


def test_load_production_rejects_nested_coerced_output_size(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("51")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [
        {
            "id": "batch-1",
            "plan_items": ["item-root"],
            "status": "completed",
            "result": {
                "outputs": [
                    {
                        "id": "out-1",
                        "type": "artifact",
                        "ref": "out.txt",
                        "sha256": "a" * 64,
                        "size": True,
                        "media_type": "text/plain",
                        "captured_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "contributions": [],
                "dispositions": {},
            },
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="size must be a non-negative integer"):
        store.load_production(run_id)


def test_load_run_rejects_malformed_plan_digest_shape(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("61")
    _create_run(store, run_id)
    run = store.load_run(run_id)
    digests = dict(run.get("digests") or {})
    digests["plan"] = "not-a-digest"
    run = dict(run)
    run["digests"] = digests
    atomic_write_json(store.run_dir(run_id) / "run.json", run)

    with pytest.raises(PersistenceError, match="digests.plan must be a 64-character"):
        store.load_run(run_id)


def test_config_only_input_ref_change_remains_resumable_after_round11(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("71")
    _create_run(store, run_id)
    config = store.load_resolved_config(run_id)
    config = dict(config)
    run_section = dict(config.get("run") or {})
    run_section["input_refs"] = ["README.md", "extra.txt"]
    config["run"] = run_section
    workspace = Path(str(store.load_run(run_id)["workspace"])).resolve()
    (workspace / "extra.txt").write_text("extra\n", encoding="utf-8")

    store.commit(run_id, CommitSpec(resolved_config=config))

    run = store.load_run(run_id)
    production = store.load_production(run_id)
    loaded_config = store.load_resolved_config(run_id)
    assert (
        validate_resume_context_bindings(
            run,
            production,
            loaded_config,
            workspace=workspace,
        )
        is None
    )
