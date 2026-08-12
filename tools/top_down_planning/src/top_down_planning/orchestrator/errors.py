"""Orchestrator-level errors."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base orchestrator error."""

    def __init__(self, message: str, *, code: str = "orchestrator_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderRunError(OrchestratorError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="provider_run_error")


class OrchestratorInvariantError(OrchestratorError):
    """Programming or policy invariant violated during orchestration."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="orchestrator_invariant_failure")


class SessionRecoveryPaused(OrchestratorError):
    """Raised after pausing a run during session replacement."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="session_recovery_paused")


class SessionRecoveryExhausted(OrchestratorError):
    """Raised after marking the run failed with session_recovery_exhausted."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="session_recovery_exhausted")


class ProducerReplacementBlocked(ProviderRunError):
    """Producer replacement blocked by workspace or evidence integrity checks."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "producer_replacement_blocked"


class ProviderTeardownError(ProviderRunError):
    """Provider or agent processes could not be torn down cleanly."""

    def __init__(
        self,
        message: str,
        *,
        surviving_pids: tuple[int, ...] = (),
        terminated_pids: tuple[int, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = "provider_teardown_error"
        self.surviving_pids = surviving_pids
        self.terminated_pids = terminated_pids


class OrphanCleanupBlocked(ProviderRunError):
    """Pre-run orphan cleanup left surviving run-associated agent processes."""

    def __init__(self, message: str, *, surviving_pids: tuple[int, ...] = ()) -> None:
        super().__init__(message)
        self.code = "orphan_cleanup_blocked"
        self.surviving_pids = surviving_pids


def coerce_provider_teardown_error(
    exc: BaseException,
    *,
    surviving_pids: tuple[int, ...] = (),
    terminated_pids: tuple[int, ...] = (),
) -> ProviderTeardownError:
    """Normalize teardown failures into a typed provider teardown error."""

    if isinstance(exc, ProviderTeardownError):
        merged_survivors = exc.surviving_pids
        if surviving_pids:
            merged_survivors = tuple(sorted({*exc.surviving_pids, *surviving_pids}))
        merged_terminated = exc.terminated_pids
        if terminated_pids:
            merged_terminated = tuple(sorted({*exc.terminated_pids, *terminated_pids}))
        if merged_survivors != exc.surviving_pids or merged_terminated != exc.terminated_pids:
            return ProviderTeardownError(
                str(exc),
                surviving_pids=merged_survivors,
                terminated_pids=merged_terminated,
            )
        return exc
    message = str(exc).strip() or exc.__class__.__name__
    return ProviderTeardownError(
        message,
        surviving_pids=surviving_pids,
        terminated_pids=terminated_pids,
    )


def provider_teardown_error_with_final_survivors(
    exc: BaseException,
    surviving_pids: tuple[int, ...],
) -> ProviderTeardownError:
    """Normalize teardown failures using the post-fallback survivor set."""

    if isinstance(exc, ProviderTeardownError):
        message = str(exc)
        terminated_pids = exc.terminated_pids
    else:
        message = str(exc).strip() or exc.__class__.__name__
        terminated_pids = ()
    return ProviderTeardownError(
        message,
        surviving_pids=surviving_pids,
        terminated_pids=terminated_pids,
    )
