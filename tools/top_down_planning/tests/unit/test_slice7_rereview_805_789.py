"""Slice 7 re-review regressions for residual 789 ownership and new 805."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.production import live_output_evidence_entries
from top_down_planning.domain.run_ownership import (
    acquire_run_ownership,
    release_run_ownership,
    resolve_run_dir,
)
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from tests.conftest import run_cli
from tests.helpers import accept_child_run
from tests.support.cli_fakes import _assert_no_traceback
from tests.unit.test_slice7_rereview_798_801 import _json_objects, _next_argv
from tests.unit.test_slice7_rereview_804_789 import _attach_argv
from tests.support.run_builders import _parent_with_orchestration


def _accepted_attach_pair(tmp_path: Path):
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
    return store, parent_id, child_id


def _first_evidence_entry(store, child_id: str) -> dict:
    entries = live_output_evidence_entries(store.load_production(child_id))
    assert entries
    return entries[0]


def _assert_attach_rejected(result, child_id: str, *, stream_json: bool) -> None:
    _assert_no_traceback(result)
    assert result.exit_code == 1
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert payload["error"]["code"] == "sub_tdp_attach_rejected"
        assert payload.get("run_id") == child_id
        assert payload.get("child_run_id") == child_id
    else:
        assert child_id in result.stderr
        assert result.stdout.strip() == "" or "Traceback" not in result.stdout


@pytest.mark.parametrize("stream_json", [True, False])
def test_attach_missing_evidence_snapshot_is_classified(
    tmp_path: Path, stream_json: bool
) -> None:
    store, parent_id, child_id = _accepted_attach_pair(tmp_path)
    entry = _first_evidence_entry(store, child_id)
    ref = Path(str(entry["snapshot_ref"]))
    snapshot = store.artifact_path(child_id, ref.parts[1], ref.parts[2])
    snapshot.unlink()
    argv = _attach_argv(tmp_path, parent_id, child_id)
    if stream_json:
        argv.append("--stream-json")
    result = run_cli(argv)
    _assert_attach_rejected(result, child_id, stream_json=stream_json)


@pytest.mark.parametrize("stream_json", [True, False])
def test_attach_evidence_hash_mismatch_is_classified(
    tmp_path: Path, stream_json: bool
) -> None:
    store, parent_id, child_id = _accepted_attach_pair(tmp_path)
    entry = _first_evidence_entry(store, child_id)
    ref = Path(str(entry["snapshot_ref"]))
    snapshot = store.artifact_path(child_id, ref.parts[1], ref.parts[2])
    snapshot.write_bytes(b"tampered evidence bytes\n")
    argv = _attach_argv(tmp_path, parent_id, child_id)
    if stream_json:
        argv.append("--stream-json")
    result = run_cli(argv)
    _assert_attach_rejected(result, child_id, stream_json=stream_json)


@pytest.mark.parametrize("stream_json", [True, False])
def test_attach_malformed_evidence_metadata_is_classified(
    tmp_path: Path, stream_json: bool
) -> None:
    store, parent_id, child_id = _accepted_attach_pair(tmp_path)
    from top_down_planning.domain.production import live_output_evidence_entries as live_entries

    def malformed_entries(production):
        return [
            {**entry, "snapshot_ref": "not-a-snapshot"}
            for entry in live_entries(production)
        ]

    argv = _attach_argv(tmp_path, parent_id, child_id)
    if stream_json:
        argv.append("--stream-json")
    with patch(
        "top_down_planning.domain.production.live_output_evidence_entries",
        malformed_entries,
    ):
        result = run_cli(argv)
    _assert_attach_rejected(result, child_id, stream_json=stream_json)


@pytest.mark.parametrize("stream_json", [True, False])
@pytest.mark.parametrize("target", ["parent", "child"])
def test_attach_ownership_conflict_recovers_conflicting_run(
    tmp_path: Path, stream_json: bool, target: str
) -> None:
    store, parent_id, child_id = _accepted_attach_pair(tmp_path)
    conflicting_id = parent_id if target == "parent" else child_id
    run_dir = resolve_run_dir(store, conflicting_id)
    assert run_dir is not None
    token = acquire_run_ownership(conflicting_id, run_dir=run_dir)
    argv = _attach_argv(tmp_path, parent_id, child_id)
    if stream_json:
        argv.append("--stream-json")
    try:
        result = run_cli(argv)
    finally:
        release_run_ownership(conflicting_id, run_dir=run_dir, owner_token=token)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    text = result.stderr + result.stdout
    assert conflicting_id in text
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert payload["error"]["code"] == "run_owned_by_live_process"
        assert payload.get("run_id") == conflicting_id
        assert payload.get("parent_run_id") == parent_id
        assert payload.get("child_run_id") == child_id
        assert payload["recovery"]["command"] == "status"
        assert payload["recovery"]["run_id"] == conflicting_id
    else:
        recovery = _next_argv(result.stderr)
        assert recovery[1] == "status"
        assert recovery[recovery.index("--run") + 1] == conflicting_id
