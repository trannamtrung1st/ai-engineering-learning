"""Slice 5 fifteenth re-review regressions (S5-RR15-001 TDP retry)."""

from __future__ import annotations

from unittest.mock import patch

from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
)
from top_down_planning.orchestrator.provider_teardown import (
    _retry_terminate_identities,
    _retry_terminate_provider_identities,
)


def test_retry_unreadable_identity_is_unresolved_not_stale() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-rr15")

    with patch(
        "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
        ) as terminate:
            result = _retry_terminate_provider_identities([identity])

    assert result.unresolved == (4242,)
    assert result.stale_reconciled == ()
    assert result.failed == ()
    terminate.assert_not_called()


def test_retry_identities_unreadable_is_unresolved_not_stale() -> None:
    identity = ProcessIdentity(pid=5151, start_time="200", run_id="run-rr15")

    with patch(
        "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ):
        result = _retry_terminate_identities([identity])

    assert result.unresolved == (5151,)
    assert result.stale_reconciled == ()


def test_retry_live_match_can_terminate_after_inspection_recovers() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-rr15")

    with patch(
        "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
            return_value=TerminateIdentityResult.TERMINATED,
        ):
            result = _retry_terminate_provider_identities([identity])

    assert result.terminated == (4242,)
    assert result.unresolved == ()
    assert result.stale_reconciled == ()
