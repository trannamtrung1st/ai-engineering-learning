"""Tests for live-process run ownership (proposal §18.1)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from top_down_planning.domain.run_ownership import (
    ResumeLockRecord,
    RunOwnershipError,
    acquire_run_ownership,
    assert_expected_run_revision,
    clear_orphan_resume_lock,
    clear_stale_resume_lock,
    is_resume_lock_stale,
    read_resume_lock,
    release_run_ownership,
    resume_lock_dir,
    resume_lock_metadata_path,
    resume_lock_path,
    run_ownership,
)


def test_assert_expected_run_revision_rejects_stale_revision() -> None:
    with pytest.raises(RunOwnershipError, match="revision is stale"):
        assert_expected_run_revision({"revision": 2}, 1)


def test_acquire_and_release_run_ownership(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    lock = read_resume_lock(run_dir)
    assert lock is not None
    assert lock.owner_token == token
    assert lock.pid == os.getpid()
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)
    assert read_resume_lock(run_dir) is None


def test_second_acquire_blocked_while_first_holds_lock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    with pytest.raises(RunOwnershipError, match="owned by a live"):
        acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_stale_lock_from_dead_pid_is_cleared(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    stale = ResumeLockRecord(
        run_id="run-1",
        pid=999999,
        owner_token="stale-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    resume_lock_path(run_dir).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert clear_stale_resume_lock(run_dir) is True
    assert read_resume_lock(run_dir) is None
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_stale_lock_by_timestamp_is_not_stale_when_pid_alive(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    old_time = (datetime.now(UTC) - timedelta(hours=5)).replace(microsecond=0)
    stale = ResumeLockRecord(
        run_id="run-1",
        pid=os.getpid(),
        owner_token="old-token",
        acquired_at=old_time.isoformat().replace("+00:00", "Z"),
    )
    resume_lock_path(run_dir).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert is_resume_lock_stale(stale, stale_after_seconds=60) is False
    assert clear_stale_resume_lock(run_dir, stale_after_seconds=60) is False


def test_malformed_resume_lock_is_not_cleared(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    resume_lock_path(run_dir).write_text("{not-json", encoding="utf-8")
    assert clear_orphan_resume_lock(run_dir) is False
    assert resume_lock_path(run_dir).is_file()


def test_empty_legacy_resume_lock_is_cleared(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    resume_lock_path(run_dir).write_text("", encoding="utf-8")
    assert clear_orphan_resume_lock(run_dir) is True
    assert read_resume_lock(run_dir) is None
    token = acquire_run_ownership("run-2", run_dir=run_dir)
    release_run_ownership("run-2", run_dir=run_dir, owner_token=token)


def test_run_ownership_context_manager_releases_on_exit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with run_ownership("run-1", run_dir=run_dir):
        assert read_resume_lock(run_dir) is not None
    assert read_resume_lock(run_dir) is None


def test_acquire_blocked_by_existing_live_on_disk_lock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    live = ResumeLockRecord(
        run_id="run-1",
        pid=os.getpid(),
        owner_token="foreign-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    resume_lock_path(run_dir).write_text(
        __import__("json").dumps(live.to_dict()) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RunOwnershipError, match="owned by live process"):
        acquire_run_ownership("run-1", run_dir=run_dir)


def test_nested_run_ownership_reuses_outer_lock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with run_ownership("run-1", run_dir=run_dir) as outer_token:
        assert read_resume_lock(run_dir) is not None
        with run_ownership("run-1", run_dir=run_dir) as inner_token:
            assert inner_token == outer_token
            assert read_resume_lock(run_dir) is not None
        assert read_resume_lock(run_dir) is not None
    assert read_resume_lock(run_dir) is None


def test_nested_run_ownership_blocks_other_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    barrier = threading.Barrier(2)
    error: list[BaseException] = []

    def competing_acquire() -> None:
        try:
            barrier.wait()
            acquire_run_ownership("run-1", run_dir=run_dir)
        except BaseException as exc:  # pragma: no cover - threaded assertion path
            error.append(exc)

    with run_ownership("run-1", run_dir=run_dir):
        thread = threading.Thread(target=competing_acquire)
        thread.start()
        barrier.wait()
        thread.join()
    assert len(error) == 1
    assert isinstance(error[0], RunOwnershipError)


def test_cross_process_acquire_blocks_while_peer_holds_lock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    holding_path = run_dir / ".child_holding"
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import time; from pathlib import Path; "
                "from top_down_planning.domain.run_ownership import "
                "acquire_run_ownership, release_run_ownership; "
                f"run_dir = Path('{run_dir_arg}'); "
                "holding = run_dir / '.child_holding'; "
                "token = acquire_run_ownership('run-1', run_dir=run_dir); "
                "holding.write_text('1', encoding='utf-8'); "
                "time.sleep(0.4); "
                "holding.unlink(missing_ok=True); "
                "release_run_ownership('run-1', run_dir=run_dir, owner_token=token)"
            ),
        ],
    )
    for _ in range(100):
        if holding_path.is_file():
            break
        time.sleep(0.02)
    assert holding_path.is_file()
    with pytest.raises(RunOwnershipError, match="owned by live process"):
        acquire_run_ownership("run-1", run_dir=run_dir)
    assert child.wait(timeout=5) == 0
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_acquire_recovers_abandoned_empty_lock_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_acquire_recovers_corrupt_metadata_from_dead_pid(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir()
    resume_lock_metadata_path(run_dir).write_text(
        '{"pid": 999999, "process_identity": "999999:0", "owner',
        encoding="utf-8",
    )
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)
