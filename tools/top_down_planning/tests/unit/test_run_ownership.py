"""Tests for live-process run ownership (proposal §18.1)."""

from __future__ import annotations

import os
import signal
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
    _rollback_failed_acquire,
    _clear_owner_metadata,
    _release_flock_fd,
)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src = Path(__file__).resolve().parents[2] / "src"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src) + (os.pathsep + existing if existing else "")
    return env


def _wait_for_peer_acquire(run_dir: Path, *, attempts: int = 100, delay: float = 0.02) -> str:
    for _ in range(attempts):
        try:
            token = acquire_run_ownership("run-1", run_dir=run_dir)
            return token
        except RunOwnershipError:
            time.sleep(delay)
    pytest.fail("peer could not acquire ownership after child exit")


def _assert_no_ownership_registry_leak() -> None:
    if not _OWNERSHIP_REGISTRY:
        return
    leaked = {run_id: dict(entry) for run_id, entry in _OWNERSHIP_REGISTRY.items()}
    for entry in leaked.values():
        try:
            _release_flock_fd(int(entry["fd"]))
        except (OSError, ValueError, TypeError):
            pass
    _OWNERSHIP_REGISTRY.clear()
    pytest.fail(f"ownership registry leak: {leaked}")


@pytest.fixture(autouse=True)
def _assert_no_ownership_leak() -> None:
    yield
    _assert_no_ownership_registry_leak()


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


def test_rollback_mismatched_token_preserves_winner_registry(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    winner_token = acquire_run_ownership("run-1", run_dir=run_dir)
    winner_entry = dict(_OWNERSHIP_REGISTRY["run-1"])
    loser_token = "loser-token"
    _rollback_failed_acquire("run-1", run_dir, loser_token, None)
    assert _OWNERSHIP_REGISTRY["run-1"] == winner_entry
    assert holds_run_ownership("run-1")
    release_run_ownership("run-1", run_dir=run_dir, owner_token=winner_token)


def test_same_process_concurrent_first_acquire_one_winner(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    barrier = threading.Barrier(2)
    results: list[tuple[str, str | BaseException]] = []

    def contender(label: str) -> None:
        try:
            barrier.wait()
            token = acquire_run_ownership("run-1", run_dir=run_dir)
            results.append((label, token))
        except BaseException as exc:
            results.append((label, exc))

    threads = [
        threading.Thread(target=contender, args=("a",)),
        threading.Thread(target=contender, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    winners = [item for item in results if not isinstance(item[1], BaseException)]
    losers = [item for item in results if isinstance(item[1], BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1
    loser_exc = losers[0][1]
    assert isinstance(loser_exc, RunOwnershipError)
    assert loser_exc.code == "run_owned_by_live_process"

    winner_token = winners[0][1]
    assert isinstance(winner_token, str)
    assert holds_run_ownership("run-1")
    assert _OWNERSHIP_REGISTRY["run-1"]["owner_token"] == winner_token

    run_dir_arg = str(run_dir)
    holding_path = run_dir / ".peer_holding"
    child_script = (
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import "
        "acquire_run_ownership, RunOwnershipError\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "holding = run_dir / '.peer_holding'\n"
        "try:\n"
        "    acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "except RunOwnershipError:\n"
        "    holding.write_text('blocked', encoding='utf-8')\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_script],
        env=_subprocess_env(),
    )
    for _ in range(100):
        if holding_path.is_file():
            break
        time.sleep(0.02)
    assert child.wait(timeout=5) == 0
    assert holding_path.read_text(encoding="utf-8") == "blocked"

    release_run_ownership("run-1", run_dir=run_dir, owner_token=winner_token)
    assert not holds_run_ownership("run-1")

    peer_token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=peer_token)


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


def test_registry_leak_helper_reports_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    acquire_run_ownership("run-1", run_dir=run_dir)
    with pytest.raises(pytest.fail.Exception, match="ownership registry leak"):
        _assert_no_ownership_registry_leak()
    assert not _OWNERSHIP_REGISTRY


def test_rollback_cleans_metadata_before_unlock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    from top_down_planning.domain import run_ownership as ownership_module

    real_publish = ownership_module._publish_run_ownership
    real_cleanup = ownership_module._cleanup_failed_acquire
    real_release = ownership_module._release_flock_fd
    order: list[str] = []

    def publish_and_fail(run_id: str, owner_token: str, flock_fd: int) -> None:
        real_publish(run_id, owner_token, flock_fd)
        raise RuntimeError("after publish")

    def record_cleanup(run_dir_arg: Path) -> None:
        order.append("cleanup")
        real_cleanup(run_dir_arg)

    def record_release(fd: int) -> None:
        order.append("unlock")
        real_release(fd)

    with patch.object(ownership_module, "_publish_run_ownership", publish_and_fail):
        with patch.object(ownership_module, "_cleanup_failed_acquire", record_cleanup):
            with patch.object(ownership_module, "_release_flock_fd", record_release):
                with pytest.raises(RuntimeError, match="after publish"):
                    acquire_run_ownership("run-1", run_dir=run_dir)
    assert order == ["cleanup", "unlock"]
    assert "run-1" not in _OWNERSHIP_REGISTRY


def test_rollback_cleanup_blocks_external_acquire_until_unlock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    from top_down_planning.domain import run_ownership as ownership_module

    real_publish = ownership_module._publish_run_ownership
    real_cleanup = ownership_module._cleanup_failed_acquire
    cleanup_started = threading.Event()
    cleanup_continue = threading.Event()
    cleanup_invocations = 0

    def publish_and_fail(run_id: str, owner_token: str, flock_fd: int) -> None:
        real_publish(run_id, owner_token, flock_fd)
        raise RuntimeError("after publish")

    def gated_cleanup(run_dir_arg: Path) -> None:
        nonlocal cleanup_invocations
        cleanup_started.set()
        if not cleanup_continue.wait(timeout=5):
            raise RuntimeError("cleanup gate timeout")
        cleanup_invocations += 1
        real_cleanup(run_dir_arg)

    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import "
        "acquire_run_ownership, RunOwnershipError\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "signal = run_dir / '.peer_try'\n"
        "while not signal.is_file():\n"
        "    time.sleep(0.001)\n"
        "try:\n"
        "    acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "    (run_dir / '.peer_success').write_text('1', encoding='utf-8')\n"
        "except RunOwnershipError:\n"
        "    (run_dir / '.peer_blocked').write_text('1', encoding='utf-8')\n"
    )

    with patch.object(ownership_module, "_publish_run_ownership", publish_and_fail):
        with patch.object(ownership_module, "_cleanup_failed_acquire", gated_cleanup):
            rollback_error: list[BaseException] = []

            def failing_acquire() -> None:
                try:
                    acquire_run_ownership("run-1", run_dir=run_dir)
                except BaseException as exc:
                    rollback_error.append(exc)

            rollback_thread = threading.Thread(target=failing_acquire)
            rollback_thread.start()
            assert cleanup_started.wait(timeout=5)

            peer_try = run_dir / ".peer_try"
            peer_try.write_text("1", encoding="utf-8")
            child = subprocess.Popen(
                [sys.executable, "-c", child_script],
                env=_subprocess_env(),
            )
            for _ in range(100):
                if (run_dir / ".peer_blocked").is_file() or (run_dir / ".peer_success").is_file():
                    break
                time.sleep(0.02)
            assert child.wait(timeout=5) == 0
            assert (run_dir / ".peer_blocked").is_file()
            assert not (run_dir / ".peer_success").is_file()

            cleanup_continue.set()
            rollback_thread.join(timeout=5)
            assert not rollback_thread.is_alive()
            assert len(rollback_error) == 1
            assert type(rollback_error[0]) is RuntimeError
            assert str(rollback_error[0]) == "after publish"
            assert cleanup_invocations == 1
            assert "run-1" not in _OWNERSHIP_REGISTRY

    peer_token = acquire_run_ownership("run-1", run_dir=run_dir)
    lock = read_resume_lock(run_dir)
    assert lock is not None
    assert lock.owner_token == peer_token
    release_run_ownership("run-1", run_dir=run_dir, owner_token=peer_token)


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


def test_child_sigint_while_holding_ownership_allows_peer_acquire(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import acquire_run_ownership\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "token = acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "(run_dir / '.acquired').write_text(token, encoding='utf-8')\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    acquired_marker = run_dir / ".acquired"
    for _ in range(100):
        if acquired_marker.is_file():
            break
        time.sleep(0.02)
    assert acquired_marker.is_file()
    with pytest.raises(RunOwnershipError):
        acquire_run_ownership("run-1", run_dir=run_dir)
    os.kill(child.pid, signal.SIGINT)
    assert child.wait(timeout=5) != 0
    token = _wait_for_peer_acquire(run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_child_sigterm_while_holding_ownership_allows_peer_acquire(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import acquire_run_ownership\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "token = acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "(run_dir / '.acquired').write_text(token, encoding='utf-8')\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    acquired_marker = run_dir / ".acquired"
    for _ in range(100):
        if acquired_marker.is_file():
            break
        time.sleep(0.02)
    assert acquired_marker.is_file()
    with pytest.raises(RunOwnershipError):
        acquire_run_ownership("run-1", run_dir=run_dir)
    os.kill(child.pid, signal.SIGTERM)
    assert child.wait(timeout=5) != 0
    token = _wait_for_peer_acquire(run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_child_sigint_during_release_attempt_allows_peer_acquire(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import "
        "acquire_run_ownership, release_run_ownership\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "token = acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "(run_dir / '.acquired').write_text(token, encoding='utf-8')\n"
        "while not (run_dir / '.go_release').is_file():\n"
        "    time.sleep(0.01)\n"
        "release_run_ownership('run-1', run_dir=run_dir, owner_token=token)\n"
        "(run_dir / '.released').write_text('1', encoding='utf-8')\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    acquired_marker = run_dir / ".acquired"
    for _ in range(100):
        if acquired_marker.is_file():
            break
        time.sleep(0.02)
    assert acquired_marker.is_file()
    (run_dir / ".go_release").write_text("1", encoding="utf-8")
    os.kill(child.pid, signal.SIGINT)
    assert child.wait(timeout=5) != 0
    assert not (run_dir / ".released").is_file()
    token = _wait_for_peer_acquire(run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_child_sigint_during_gated_acquire_metadata_allows_peer_acquire(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from unittest.mock import patch\n"
        "from top_down_planning.domain import run_ownership as ownership_module\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "real_write = ownership_module._write_lock_metadata\n"
        "def gated(path, record):\n"
        "    (run_dir / '.inside_acquire').write_text('1', encoding='utf-8')\n"
        "    while not (run_dir / '.go').is_file():\n"
        "        time.sleep(0.01)\n"
        "    return real_write(path, record)\n"
        "try:\n"
        "    with patch.object(ownership_module, '_write_lock_metadata', gated):\n"
        "        ownership_module.acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "except BaseException:\n"
        "    pass\n"
        "(run_dir / '.done').write_text('1', encoding='utf-8')\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    inside = run_dir / ".inside_acquire"
    for _ in range(100):
        if inside.is_file():
            break
        time.sleep(0.02)
    assert inside.is_file()
    os.kill(child.pid, signal.SIGINT)
    assert child.wait(timeout=5) == 0
    assert "run-1" not in _OWNERSHIP_REGISTRY
    token = _wait_for_peer_acquire(run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_child_sigterm_during_gated_release_unlock_allows_peer_acquire(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from unittest.mock import patch\n"
        "from top_down_planning.domain import run_ownership as ownership_module\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "token = ownership_module.acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "(run_dir / '.acquired').write_text(token, encoding='utf-8')\n"
        "while not (run_dir / '.go_release').is_file():\n"
        "    time.sleep(0.01)\n"
        "real_release = ownership_module._release_flock_fd\n"
        "def gated(fd):\n"
        "    (run_dir / '.inside_release').write_text('1', encoding='utf-8')\n"
        "    while not (run_dir / '.go').is_file():\n"
        "        time.sleep(0.01)\n"
        "    return real_release(fd)\n"
        "try:\n"
        "    with patch.object(ownership_module, '_release_flock_fd', gated):\n"
        "        ownership_module.release_run_ownership(\n"
        "            'run-1', run_dir=run_dir, owner_token=token,\n"
        "        )\n"
        "except BaseException:\n"
        "    pass\n"
        "(run_dir / '.done').write_text('1', encoding='utf-8')\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    acquired_marker = run_dir / ".acquired"
    for _ in range(100):
        if acquired_marker.is_file():
            break
        time.sleep(0.02)
    assert acquired_marker.is_file()
    (run_dir / ".go_release").write_text("1", encoding="utf-8")
    inside = run_dir / ".inside_release"
    for _ in range(100):
        if inside.is_file():
            break
        time.sleep(0.02)
    assert inside.is_file()
    os.kill(child.pid, signal.SIGTERM)
    (run_dir / ".go").write_text("1", encoding="utf-8")
    assert child.wait(timeout=5) == 0
    assert (run_dir / ".done").is_file()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_double_sigint_during_gated_release_unlock_completes_and_peer_acquires(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from unittest.mock import patch\n"
        "from top_down_planning.domain import run_ownership as ownership_module\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "token = ownership_module.acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "(run_dir / '.acquired').write_text(token, encoding='utf-8')\n"
        "while not (run_dir / '.go_release').is_file():\n"
        "    time.sleep(0.01)\n"
        "real_release = ownership_module._release_flock_fd\n"
        "def gated(fd):\n"
        "    (run_dir / '.inside_release').write_text('1', encoding='utf-8')\n"
        "    while not (run_dir / '.go').is_file():\n"
        "        time.sleep(0.01)\n"
        "    return real_release(fd)\n"
        "with patch.object(ownership_module, '_release_flock_fd', gated):\n"
        "    ownership_module.release_run_ownership(\n"
        "        'run-1', run_dir=run_dir, owner_token=token,\n"
        "    )\n"
        "(run_dir / '.released').write_text('1', encoding='utf-8')\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    acquired_marker = run_dir / ".acquired"
    for _ in range(100):
        if acquired_marker.is_file():
            break
        time.sleep(0.02)
    (run_dir / ".go_release").write_text("1", encoding="utf-8")
    inside = run_dir / ".inside_release"
    for _ in range(100):
        if inside.is_file():
            break
        time.sleep(0.02)
    os.kill(child.pid, signal.SIGINT)
    os.kill(child.pid, signal.SIGINT)
    (run_dir / ".go").write_text("1", encoding="utf-8")
    assert child.wait(timeout=5) == 0
    assert (run_dir / ".released").is_file()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_run_ownership_import_requires_posix_fcntl_subprocess() -> None:
    child_script = (
        "import builtins\n"
        "_real_import = builtins.__import__\n"
        "def _block_fcntl(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    if name == 'fcntl':\n"
        "        raise ImportError('no fcntl module')\n"
        "    return _real_import(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = _block_fcntl\n"
        "try:\n"
        "    import importlib\n"
        "    import top_down_planning.domain.run_ownership as mod\n"
        "    importlib.reload(mod)\n"
        "except ImportError as exc:\n"
        "    msg = str(exc)\n"
        "    if 'POSIX' in msg or 'fcntl' in msg:\n"
        "        raise SystemExit(0)\n"
        "    raise\n"
        "raise SystemExit(2)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    assert child.wait(timeout=10) == 0


def test_flock_holder_blocks_peer_despite_stale_unknown_identity_metadata(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    run_dir_arg = str(run_dir)
    child_script = (
        "import time\n"
        "from pathlib import Path\n"
        "from top_down_planning.domain.run_ownership import acquire_run_ownership\n"
        f"run_dir = Path('{run_dir_arg}')\n"
        "token = acquire_run_ownership('run-1', run_dir=run_dir)\n"
        "(run_dir / '.acquired').write_text(token, encoding='utf-8')\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_script], env=_subprocess_env())
    acquired_marker = run_dir / ".acquired"
    for _ in range(100):
        if acquired_marker.is_file():
            break
        time.sleep(0.02)
    stale = ResumeLockRecord(
        run_id="run-1",
        pid=999999,
        owner_token="stale-unknown",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        process_identity="999999:unknown",
    )
    resume_lock_metadata_path(run_dir).parent.mkdir(parents=True, exist_ok=True)
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(stale.to_dict()) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RunOwnershipError):
        acquire_run_ownership("run-1", run_dir=run_dir)
    os.kill(child.pid, signal.SIGTERM)
    assert child.wait(timeout=5) != 0
    token = _wait_for_peer_acquire(run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_process_identity_unknown_without_proc_filesystem() -> None:
    pid = os.getpid()
    with patch(
        "top_down_planning.domain.run_ownership.os.stat",
        side_effect=OSError("no proc"),
    ):
        assert process_identity_for_pid(pid) == f"{pid}:unknown"


def test_legacy_unknown_identity_conservatively_blocks_acquire_without_flock(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    pid = os.getpid()
    unknown = f"{pid}:unknown"
    legacy = ResumeLockRecord(
        run_id="run-1",
        pid=pid,
        owner_token="legacy-unknown",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        process_identity=unknown,
    )
    resume_lock_path(run_dir).write_text(
        __import__("json").dumps(legacy.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert not owner_flock_path(run_dir).is_file()
    with patch(
        "top_down_planning.domain.run_ownership.process_identity_for_pid",
        return_value=unknown,
    ):
        assert is_resume_lock_stale(legacy) is False
        with pytest.raises(RunOwnershipError, match="owned"):
            acquire_run_ownership("run-1", run_dir=run_dir)


def test_legacy_unknown_identity_clears_when_pid_dead_allows_acquire(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    dead_pid = 999999991
    unknown = f"{dead_pid}:unknown"
    legacy = ResumeLockRecord(
        run_id="run-1",
        pid=dead_pid,
        owner_token="legacy-dead-unknown",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        process_identity=unknown,
    )
    resume_lock_path(run_dir).write_text(
        __import__("json").dumps(legacy.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert is_resume_lock_stale(legacy) is True
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_mismatched_process_identity_treated_as_stale_holder(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    live = ResumeLockRecord(
        run_id="run-1",
        pid=os.getpid(),
        owner_token="stale-identity-token",
        acquired_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        process_identity="999999:0",
    )
    resume_lock_metadata_path(run_dir).parent.mkdir(parents=True, exist_ok=True)
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(live.to_dict()) + "\n",
        encoding="utf-8",
    )
    assert is_resume_lock_stale(live) is True
    assert clear_stale_resume_lock(run_dir) is True
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


def test_wrong_token_release_preserves_owner_metadata_on_disk(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    token = acquire_run_ownership("run-1", run_dir=run_dir)
    lock_before = read_resume_lock(run_dir)
    assert lock_before is not None
    release_run_ownership("run-1", run_dir=run_dir, owner_token="foreign-token")
    lock_after = read_resume_lock(run_dir)
    assert lock_after is not None
    assert lock_after.owner_token == lock_before.owner_token
    assert lock_after.pid == lock_before.pid
    release_run_ownership("run-1", run_dir=run_dir, owner_token=token)


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
