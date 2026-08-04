"""Tests for live-process run ownership (proposal §18.1)."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from top_down_planning.domain.run_ownership import (
    ResumeLockRecord,
    RunOwnershipError,
    acquire_run_ownership,
    assert_expected_run_revision,
    clear_stale_resume_lock,
    is_resume_lock_stale,
    read_resume_lock,
    release_run_ownership,
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
    acquire_run_ownership("run-1", run_dir=run_dir)


def test_stale_lock_by_timestamp_is_cleared(tmp_path: Path) -> None:
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
    assert is_resume_lock_stale(stale, stale_after_seconds=60) is True
    assert clear_stale_resume_lock(run_dir, stale_after_seconds=60) is True


def test_run_ownership_context_manager_releases_on_exit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with run_ownership("run-1", run_dir=run_dir):
        assert read_resume_lock(run_dir) is not None
    assert read_resume_lock(run_dir) is None


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
