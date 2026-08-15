"""Slice 5 rereview 568f97b: absolute identity deadline and Windows fail-fast."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderUnsupportedPlatformError
from core_tools.provider.factory import create_provider
from core_tools.provider.process_cleanup import terminate_process_tree
from core_tools.provider.process_identity import (
    ProcessIdentity,
    _any_identities_still_alive,
    _wait_identities_dead,
    read_process_start_time,
)
from core_tools.provider.session_janitor import CleanupDeadline


def _idle_config() -> dict:
    return {
        "provider": {"name": "cursor"},
        "limits": {"provider": {"turn_idle_timeout_seconds": 0.08, "max_retries_per_call": 0}},
    }


def test_sequential_identity_scans_share_one_aggregate_deadline() -> None:
    identities = [ProcessIdentity(pid=index, start_time="1") for index in range(10)]
    seen: list[float | None] = []

    def fake_alive(identity, timeout=None):
        del identity
        seen.append(timeout)
        if timeout is not None and timeout <= 0:
            return False
        time.sleep(0.03)
        return False

    started = time.monotonic()
    with patch(
        "core_tools.provider.process_identity._identity_still_alive",
        side_effect=fake_alive,
    ):
        assert _any_identities_still_alive(identities, timeout=0.2) is False
    elapsed = time.monotonic() - started
    assert elapsed <= 0.28
    assert seen[0] is not None and seen[0] <= 0.2
    assert seen[-1] is not None
    assert seen[-1] < seen[0]
    assert seen[-1] <= 0.05


def test_wait_dead_does_not_reset_per_identity_timeout() -> None:
    identities = [ProcessIdentity(pid=index, start_time="1") for index in range(4)]
    seen: list[float | None] = []

    def fake_any(targets, timeout=None):
        del targets
        seen.append(timeout)
        time.sleep(0.04)
        return True

    started = time.monotonic()
    with patch(
        "core_tools.provider.process_identity._any_identities_still_alive",
        side_effect=fake_any,
    ):
        assert _wait_identities_dead(identities, timeout=0.15) is False
    assert time.monotonic() - started <= 1.0
    assert seen[0] is not None and seen[0] <= 0.15
    if len(seen) > 1:
        assert seen[-1] is not None
        assert seen[-1] <= seen[0]


def test_start_time_liveness_and_token_share_one_deadline() -> None:
    seen: list[float] = []

    def fake_alive(pid, timeout=None):
        del pid
        if timeout is not None:
            seen.append(timeout)
        time.sleep(0.05)
        return True

    def fake_token(pid, deadline=None):
        del pid
        remaining = None if deadline is None else deadline.remaining()
        if remaining is not None:
            seen.append(remaining)
        assert isinstance(deadline, CleanupDeadline) or deadline is None
        return "token"

    with patch(
        "core_tools.provider.process_identity.is_pid_alive",
        side_effect=fake_alive,
    ), patch(
        "core_tools.provider.process_identity.os.path.isdir",
        return_value=False,
    ), patch(
        "core_tools.provider.session_janitor._process_start_token",
        side_effect=fake_token,
    ):
        assert read_process_start_time(99, timeout=0.2) == "token"
    assert len(seen) >= 2
    assert seen[1] <= seen[0] - 0.03


def test_cursor_provider_rejects_windows(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    with patch("core_tools.provider.cursor.sys.platform", "win32"):
        with pytest.raises(ProviderUnsupportedPlatformError, match="POSIX"):
            CursorProvider(
                _idle_config(),
                workspace=tmp_path,
                runner=lambda argv, cwd: iter(()),
                binary=str(agent),
                skip_probe=True,
            )


def test_create_provider_rejects_windows_cursor(tmp_path: Path) -> None:
    with patch("core_tools.provider.factory.sys.platform", "win32"), patch(
        "core_tools.provider.cursor.sys.platform", "win32"
    ):
        with pytest.raises(ProviderUnsupportedPlatformError):
            create_provider(_idle_config(), workspace=tmp_path)


def test_windows_process_tree_raises_typed_unsupported() -> None:
    with patch("core_tools.provider.process_cleanup.sys.platform", "win32"):
        with pytest.raises(ProviderUnsupportedPlatformError, match="POSIX"):
            terminate_process_tree(object(), timeout=0.1)  # type: ignore[arg-type]
