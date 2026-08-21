"""Prepare a deterministic tdp subprocess for OS-signal CLI tests.

When ``TDP_STUB_TURN_READY_PATH`` is set, stub host-wide orphan scans at every
import site (the same isolation the pytest session uses) and block the first
stub provider turn after writing the ready file so the parent can send SIGINT.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

_READY = os.environ.get("TDP_STUB_TURN_READY_PATH")
if _READY:
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})

    from core_tools.provider.stub import StubProvider
    from top_down_planning.orchestrator.agent_process_cleanup import OrphanScanResult
    import top_down_planning.cli.doctor as doctor
    import top_down_planning.orchestrator.agent_process_cleanup as agent_process_cleanup
    import top_down_planning.orchestrator.provider_teardown as provider_teardown
    import top_down_planning.orchestrator.run_lifecycle_reconciliation as reconciliation

    def _empty_orphan_scan(*_args: object, **_kwargs: object) -> OrphanScanResult:
        return OrphanScanResult(kill_candidates=(), unverifiable_pids=())

    def _empty_orphan_pids(*_args: object, **_kwargs: object) -> list[int]:
        return []

    agent_process_cleanup.scan_orphan_agents = _empty_orphan_scan
    agent_process_cleanup.scan_orphan_agent_pids = _empty_orphan_pids
    provider_teardown.scan_orphan_agents = _empty_orphan_scan
    provider_teardown.scan_orphan_agent_pids = _empty_orphan_pids
    reconciliation.scan_orphan_agent_pids = _empty_orphan_pids
    doctor.scan_orphan_agent_pids = _empty_orphan_pids

    def _block_then_script(self: StubProvider, session_id: str) -> list[dict[str, object]]:
        del self, session_id
        Path(_READY).write_text("ready\n", encoding="utf-8")
        time.sleep(float(os.environ.get("TDP_STUB_TURN_BLOCK_SECONDS", "30")))
        return [{"type": "done", "subtype": "success", "text": "stub turn timed out"}]

    StubProvider._resolve_script = _block_then_script  # type: ignore[method-assign]
