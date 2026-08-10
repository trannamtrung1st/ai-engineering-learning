"""Tests for live-process run ownership (proposal §18.1)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import fcntl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.run_ownership import (
    ResumeLockRecord,
    RunOwnershipError,
    acquire_run_ownership,
    assert_expected_run_revision,
    clear_orphan_resume_lock,
    clear_stale_resume_lock,
    holds_run_ownership,
    is_resume_lock_stale,
    is_run_orchestrator_alive,
    process_identity_for_pid,
    read_resume_lock,
    release_run_ownership,
    resume_lock_dir,
    resume_lock_metadata_path,
    resume_lock_path,
    owner_flock_path,
    run_ownership,
    ownership_cleanup_failures,
    _OWNERSHIP_REGISTRY,
    _OWNERSHIP_CLEANUP_FAILURES,
    _clear_owner_metadata,
    _release_flock_fd,
)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src = Path(__file__).resolve().parents[2] / "src"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src) + (os.pathsep + existing if existing else "")
    return env


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
        env=_subprocess_env(),
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


def test_orphan_lock_not_cleared_while_owner_flock_held(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir()
    owner_flock_path(run_dir).touch()
    flock_fd = os.open(owner_flock_path(run_dir), os.O_RDWR)
    fcntl.flock(flock_fd, fcntl.LOCK_EX)
    resume_lock_metadata_path(run_dir).write_text("", encoding="utf-8")
    assert clear_orphan_resume_lock(run_dir) is False
    fcntl.flock(flock_fd, fcntl.LOCK_UN)
    os.close(flock_fd)


def test_acquire_releases_flock_on_metadata_write_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with patch("top_down_planning.domain.run_ownership.os.write", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            acquire_run_ownership("run-1", run_dir=run_dir)
    assert "run-1" not in _OWNERSHIP_REGISTRY
    assert not holds_run_ownership("run-1")
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_acquire_releases_flock_on_metadata_fsync_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with patch("top_down_planning.domain.run_ownership.os.fsync", side_effect=OSError("fsync failed")):
        with pytest.raises(OSError, match="fsync failed"):
            acquire_run_ownership("run-1", run_dir=run_dir)
    assert "run-1" not in _OWNERSHIP_REGISTRY
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_simultaneous_first_acquire_exactly_one_succeeds(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    signal_path = run_dir / ".go"
    release_path = run_dir / ".release"
    child_script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import "
        "acquire_run_ownership, release_run_ownership, RunOwnershipError\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "role = sys.argv[1]\n"
        "signal = run_dir / '.go'\n"
        "release_signal = run_dir / '.release'\n"
        "while not signal.is_file():\n"
        "    time.sleep(0.001)\n"
        "try:\n"
        "    token = acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "    (run_dir / f'success_{role}').write_text(token, encoding='utf-8')\n"
        "    (run_dir / f'done_{role}').write_text('1', encoding='utf-8')\n"
        "    while not release_signal.is_file():\n"
        "        time.sleep(0.001)\n"
        "    release_run_ownership('run-1', run_dir=run_dir, owner_token=token)\n"
        "except RunOwnershipError:\n"
        "    (run_dir / f'conflict_{role}').write_text('1', encoding='utf-8')\n"
        "    (run_dir / f'done_{role}').write_text('1', encoding='utf-8')\n"
    )
    child_a = subprocess.Popen([sys.executable, "-c", child_script, "a"], env=_subprocess_env())
    child_b = subprocess.Popen([sys.executable, "-c", child_script, "b"], env=_subprocess_env())
    time.sleep(0.05)
    signal_path.write_text("go", encoding="utf-8")
    for _ in range(200):
        if (run_dir / "done_a").is_file() and (run_dir / "done_b").is_file():
            break
        time.sleep(0.01)
    assert (run_dir / "done_a").is_file()
    assert (run_dir / "done_b").is_file()
    successes = [run_dir / "success_a", run_dir / "success_b"]
    conflicts = [run_dir / "conflict_a", run_dir / "conflict_b"]
    assert sum(path.is_file() for path in successes) == 1
    assert sum(path.is_file() for path in conflicts) == 1
    release_path.write_text("release", encoding="utf-8")
    assert child_a.wait(timeout=10) == 0
    assert child_b.wait(timeout=10) == 0


def test_owner_lock_inode_stable_across_acquire_release(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    inode_acquired = owner_flock_path(run_dir).stat().st_ino
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)
    assert owner_flock_path(run_dir).is_file()
    inode_released = owner_flock_path(run_dir).stat().st_ino
    assert inode_acquired == inode_released
    token2 = acquire_run_ownership("run-1", run_dir=run_dir)
    inode_second = owner_flock_path(run_dir).stat().st_ino
    assert inode_second == inode_acquired
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token2)


def test_stale_cleanup_preserves_owner_lock_inode(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir(parents=True)
    flock_path = owner_flock_path(run_dir)
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    os.close(fd)
    inode_before = flock_path.stat().st_ino
    stale = ResumeLockRecord(
        run_id="run-1",
        pid=999999,
        owner_token="stale-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert clear_stale_resume_lock(run_dir) is True
    assert flock_path.stat().st_ino == inode_before
    assert read_resume_lock(run_dir) is None
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    assert flock_path.stat().st_ino == inode_before
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_release_run_ownership_clears_metadata_before_unlock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token_a = acquire_run_ownership("run-1", run_dir=run_dir)
    metadata_cleared = threading.Event()
    release_gate = threading.Event()

    def clear_and_signal(run_dir_arg: Path) -> bool:
        result = _clear_owner_metadata(run_dir_arg)
        metadata_cleared.set()
        return result

    def gated_release(fd: int) -> None:
        release_gate.wait(timeout=5)
        _release_flock_fd(fd)

    with patch(
        "top_down_planning.domain.run_ownership._clear_owner_metadata",
        side_effect=clear_and_signal,
    ):
        with patch(
            "top_down_planning.domain.run_ownership._release_flock_fd",
            side_effect=gated_release,
        ):
            releaser = threading.Thread(
                target=release_run_ownership,
                args=("run-1",),
                kwargs={"run_dir": run_dir, "owner_token": token_a},
            )
            releaser.start()
            assert metadata_cleared.wait(timeout=5)
            with pytest.raises(RunOwnershipError, match="owned"):
                acquire_run_ownership("run-1", run_dir=run_dir)
            release_gate.set()
            releaser.join(timeout=5)
            assert not releaser.is_alive()

    token_b = acquire_run_ownership("run-1", run_dir=run_dir)
    assert read_resume_lock(run_dir) is not None
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token_b)


def test_acquire_succeeds_when_flock_free_and_stale_live_pid_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir(parents=True)
    flock_path = owner_flock_path(run_dir)
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    os.close(fd)
    live = ResumeLockRecord(
        run_id="run-1",
        pid=os.getpid(),
        owner_token="stale-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        process_identity=process_identity_for_pid(os.getpid()),
    )
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(live.to_dict()) + "\n",
        encoding="utf-8",
    )
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    lock = read_resume_lock(run_dir)
    assert lock is not None
    assert lock.owner_token == token
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_wrong_token_release_does_not_unlock_flock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token_a = acquire_run_ownership("run-1", run_dir=run_dir)
    entry = _OWNERSHIP_REGISTRY["run-1"]
    token_b = "replacement-token"
    _OWNERSHIP_REGISTRY["run-1"] = {"owner_token": token_b, "fd": entry["fd"]}
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token_a)
    assert _OWNERSHIP_REGISTRY["run-1"]["owner_token"] == token_b
    assert "run-1" in _OWNERSHIP_REGISTRY
    with pytest.raises(RunOwnershipError, match="owned"):
        acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token_b)


def test_flock_oserror_does_not_leak_fd_or_registry(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with patch("fcntl.flock", side_effect=OSError("flock unsupported")):
        with pytest.raises(OSError, match="flock unsupported"):
            acquire_run_ownership("run-1", run_dir=run_dir)
    assert "run-1" not in _OWNERSHIP_REGISTRY
    assert not holds_run_ownership("run-1")
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_acquire_interrupt_during_metadata_write_rolls_back(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with patch(
        "top_down_planning.domain.run_ownership._write_lock_metadata",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(KeyboardInterrupt):
            acquire_run_ownership("run-1", run_dir=run_dir)
    assert not holds_run_ownership("run-1")
    assert "run-1" not in _OWNERSHIP_REGISTRY
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_acquire_interrupt_after_publication_rolls_back(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    from top_down_planning.domain import run_ownership as ownership_module

    real_publish = ownership_module._publish_run_ownership

    def publish_and_interrupt(run_id: str, owner_token: str, flock_fd: int) -> None:
        real_publish(run_id, owner_token, flock_fd)
        raise KeyboardInterrupt

    with patch.object(ownership_module, "_publish_run_ownership", publish_and_interrupt):
        with pytest.raises(KeyboardInterrupt):
            acquire_run_ownership("run-1", run_dir=run_dir)
    assert not holds_run_ownership("run-1")
    assert "run-1" not in _OWNERSHIP_REGISTRY
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_run_ownership_context_survives_metadata_cleanup_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    _OWNERSHIP_CLEANUP_FAILURES.clear()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    with patch(
        "top_down_planning.domain.run_ownership._clear_owner_metadata",
        side_effect=OSError("unlink failed"),
    ):
        release_run_ownership("run-1", run_dir=run_dir, owner_token=token)
    assert not holds_run_ownership("run-1")
    failures = ownership_cleanup_failures()
    assert len(failures) == 1
    assert failures[0]["type"] == "ownership_cleanup_failed"
    assert failures[0]["run_id"] == "run-1"
    assert failures[0]["error_class"] == "OSError"
    token2 = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token2)


def test_stale_cleanup_in_other_run_dir_does_not_clear_active_registry(tmp_path: Path) -> None:
    run_dir_a = tmp_path / "run-a"
    run_dir_b = tmp_path / "run-b"
    run_dir_a.mkdir()
    run_dir_b.mkdir()
    token_b = acquire_run_ownership("run-b", run_dir=run_dir_b)
    stale = ResumeLockRecord(
        run_id="run-b",
        pid=999999,
        owner_token="stale-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    resume_lock_dir(run_dir_a).mkdir(parents=True)
    resume_lock_metadata_path(run_dir_a).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert clear_stale_resume_lock(run_dir_a) is True
    assert holds_run_ownership("run-b")
    assert "run-b" in _OWNERSHIP_REGISTRY
    release_run_ownership("run-b", run_dir=run_dir_b, owner_token=token_b)


def test_stale_cleanup_while_holding_flock_preserves_registry(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    stale = ResumeLockRecord(
        run_id="run-1",
        pid=999999,
        owner_token="stale-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert clear_stale_resume_lock(run_dir) is False
    assert holds_run_ownership("run-1")
    assert "run-1" in _OWNERSHIP_REGISTRY
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_release_interrupt_during_flock_unlock_clears_registry_and_reacquires(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    original_flock = fcntl.flock

    def flock_with_interrupt(fd: int, op: int) -> None:
        if op == fcntl.LOCK_UN:
            raise KeyboardInterrupt
        original_flock(fd, op)

    with patch("fcntl.flock", side_effect=flock_with_interrupt):
        with pytest.raises(KeyboardInterrupt):
            release_run_ownership("run-1", run_dir=run_dir, owner_token=token)
    assert "run-1" not in _OWNERSHIP_REGISTRY
    assert not holds_run_ownership("run-1")
    token2 = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token2)


def test_is_run_orchestrator_alive_true_when_flock_held_with_dead_metadata(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir(parents=True)
    flock_path = owner_flock_path(run_dir)
    flock_fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(flock_fd, fcntl.LOCK_EX)
    stale = ResumeLockRecord(
        run_id="run-1",
        pid=999999,
        owner_token="stale-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert is_run_orchestrator_alive(run_dir) is True
    fcntl.flock(flock_fd, fcntl.LOCK_UN)
    os.close(flock_fd)
