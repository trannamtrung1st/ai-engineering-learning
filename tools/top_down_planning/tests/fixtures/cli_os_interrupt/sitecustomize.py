"""Prepare deterministic tdp subprocesses for OS-signal CLI tests.

When ``TDP_STUB_TURN_READY_PATH`` is set without ``TDP_WOR_SCRIPT``, block the
first stub provider turn after writing the ready file so the parent can send
SIGINT.

When ``TDP_WOR_SCRIPT`` and ``TDP_WOR_RUNS_DIR`` are set, script whole-output
mandatory-review resume turns instead of blocking every turn.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

_READY = os.environ.get("TDP_STUB_TURN_READY_PATH")
_WOR_SCRIPT = os.environ.get("TDP_WOR_SCRIPT")
_WOR_RUNS_DIR = os.environ.get("TDP_WOR_RUNS_DIR")
_OWNER_COUNT_PATH = os.environ.get("TDP_WOR_OWNER_TURN_COUNT_PATH")

if _READY or (_WOR_SCRIPT and _WOR_RUNS_DIR):
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

    if _WOR_SCRIPT and _WOR_RUNS_DIR:
        from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW

        def _store():
            from top_down_planning.persistence import FileRunStore

            return FileRunStore(Path(_WOR_RUNS_DIR))

        def _run_id(store):
            from tests.helpers import only_run_id

            return only_run_id(store)

        def _whole_output_loop(store, run_id: str) -> dict:
            for payload in reversed(store.list_reviews(run_id)):
                if payload.get("type") == "whole_output":
                    return dict(payload)
            return {}

        def _is_owner_revision_turn(store, session) -> bool:
            run_id = _run_id(store)
            run = store.load_run(run_id)
            if str(run.get("phase") or "") != WHOLE_OUTPUT_REVIEW:
                return False
            if session.role != "producer" or session.kind != "primary":
                return False
            loop = _whole_output_loop(store, run_id)
            return (
                loop.get("lifecycle_status") == "revision_in_progress"
                and loop.get("status") == "pending"
            )

        def _record_owner_turn() -> None:
            if not _OWNER_COUNT_PATH:
                return
            path = Path(_OWNER_COUNT_PATH)
            current = 0
            if path.is_file():
                current = int(path.read_text(encoding="utf-8").strip() or "0")
            path.write_text(str(current + 1), encoding="utf-8")

        def _owner_apply_mutate(store) -> None:
            from tests.helpers import apply_production

            run_id = _run_id(store)
            base_revision = int(store.load_production(run_id)["revision"])
            apply_production(
                store,
                run_id,
                {
                    "production_revision": base_revision,
                    "evidence_revision": True,
                    "plan_items": ["item-leaf"],
                    "dispositions": {
                        "item-leaf": {
                            "disposition": "completed",
                            "evidence": "Addressed finding.",
                        }
                    },
                    "outputs": [
                        {
                            "id": "output-leaf",
                            "type": "artifact",
                            "ref": "artifacts/leaf.txt",
                        }
                    ],
                    "contributions": [
                        {
                            "item_id": "item-leaf",
                            "output_refs": ["output-leaf"],
                            "summary": "Revised output.",
                        }
                    ],
                    "summary": "Owner revision after interrupt.",
                },
                handler="apply",
                phase=WHOLE_OUTPUT_REVIEW,
            )()
            apply_production(
                store,
                run_id,
                {
                    "goal_assessment": "Output goal is fully met after owner revision.",
                },
                handler="submit_completion",
                phase=WHOLE_OUTPUT_REVIEW,
            )()

        def _verification_respond_mutate(store) -> None:
            from tests.helpers import mandatory_verification_respond_request, respond_review

            run_id = _run_id(store)
            loop = _whole_output_loop(store, run_id)
            loop_id = str(loop.get("id") or "review-whole-output-01")
            target_revision = int(store.load_production(run_id)["output_revision"])
            finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
            respond_review(
                store,
                run_id,
                mandatory_verification_respond_request(
                    store,
                    run_id,
                    loop_id=loop_id,
                    target_revision=target_revision,
                    review_type="whole_output",
                    finding_set_id=finding_set_id,
                    finding_results=[
                        {
                            "finding_id": "finding-01",
                            "disposition": "resolved",
                            "evidence": ["fixed after resume"],
                            "direct_side_effects": [],
                        }
                    ],
                ),
                phase=WHOLE_OUTPUT_REVIEW,
                loop_id=loop_id,
            )()

        def _scope_clear_mutate(store) -> None:
            from tests.helpers import mandatory_scope_review_respond_request, respond_review

            run_id = _run_id(store)
            loop = _whole_output_loop(store, run_id)
            loop_id = str(loop.get("id") or "review-whole-output-01")
            target_revision = int(store.load_production(run_id)["output_revision"])
            respond_review(
                store,
                run_id,
                mandatory_scope_review_respond_request(
                    store,
                    run_id,
                    loop_id=loop_id,
                    target_revision=target_revision,
                    review_type="whole_output",
                ),
                phase=WHOLE_OUTPUT_REVIEW,
                loop_id=loop_id,
            )()

        def _wor_resolve_script(self: StubProvider, session_id: str) -> list[dict[str, object]]:
            session = self._require_session(session_id)
            last = session.history[-1] if session.history else {}
            store = _store()
            script = _WOR_SCRIPT or ""

            if script == "block_owner_revision":
                if _is_owner_revision_turn(store, session):
                    if _READY:
                        Path(_READY).write_text("ready\n", encoding="utf-8")
                    time.sleep(float(os.environ.get("TDP_STUB_TURN_BLOCK_SECONDS", "30")))
                    return [{"type": "done", "subtype": "success", "text": "owner blocked"}]
                if last.get("kind") == "start":
                    return [{"type": "done", "subtype": "success", "text": "session start"}]
                raise RuntimeError(
                    f"block_owner_revision: unexpected turn role={session.role} "
                    f"kind={session.kind} last={last!r}"
                )

            if last.get("kind") == "start":
                return [{"type": "done", "subtype": "success", "text": "session start"}]

            if script == "owner_then_verify":
                if session.role == "producer" and session.kind == "primary":
                    if _is_owner_revision_turn(store, session):
                        _record_owner_turn()
                        session.pending_hook = _owner_apply_mutate(store)
                        return [{"type": "done", "subtype": "success", "text": "owner revision"}]
                if session.role == "reviewer":
                    loop = _whole_output_loop(store, _run_id(store))
                    stage = str(loop.get("active_stage") or "")
                    if stage == "finding_verification":
                        session.pending_hook = _verification_respond_mutate(store)
                        return [{"type": "done", "subtype": "success", "text": "verification"}]
                    if stage == "scope_review" or loop.get("lifecycle_status") == (
                        "findings_closed"
                    ):
                        session.pending_hook = _scope_clear_mutate(store)
                        return [{"type": "done", "subtype": "success", "text": "scope review"}]
                return [{"type": "done", "subtype": "success", "text": "turn complete"}]

            if script == "artifact_advanced_verify_only":
                if session.role == "producer" and session.kind == "primary":
                    if _is_owner_revision_turn(store, session):
                        _record_owner_turn()
                        raise RuntimeError(
                            "artifact_advanced_verify_only: owner revision turn was started"
                        )
                if session.role == "reviewer":
                    loop = _whole_output_loop(store, _run_id(store))
                    stage = str(loop.get("active_stage") or "")
                    if stage == "finding_verification":
                        return [
                            {
                                "type": "done",
                                "subtype": "success",
                                "text": "verification recheck delivered",
                            }
                        ]
                    return [{"type": "done", "subtype": "success", "text": "reviewer noop"}]
                raise RuntimeError(
                    f"artifact_advanced_verify_only: unexpected turn role={session.role}"
                )

            raise RuntimeError(f"unknown TDP_WOR_SCRIPT={script!r}")

        StubProvider._resolve_script = _wor_resolve_script  # type: ignore[method-assign]
    elif _READY:

        def _block_then_script(self: StubProvider, session_id: str) -> list[dict[str, object]]:
            del self, session_id
            Path(_READY).write_text("ready\n", encoding="utf-8")
            time.sleep(float(os.environ.get("TDP_STUB_TURN_BLOCK_SECONDS", "30")))
            return [{"type": "done", "subtype": "success", "text": "stub turn timed out"}]

        StubProvider._resolve_script = _block_then_script  # type: ignore[method-assign]
