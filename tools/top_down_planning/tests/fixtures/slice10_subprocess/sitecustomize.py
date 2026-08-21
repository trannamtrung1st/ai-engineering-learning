"""Deterministic stub-provider scripting for Slice 10 OS-process tests.

Activated only when ``TDP_SLICE10_SCRIPT`` is set. Child processes share the
durable runs directory and nothing else.
"""

from __future__ import annotations

import os
import signal
import time
import uuid
from pathlib import Path

_SCRIPT = os.environ.get("TDP_SLICE10_SCRIPT")

if _SCRIPT:
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

    def _store():
        from top_down_planning.persistence import FileRunStore

        return FileRunStore(Path(os.environ["TDP_SLICE10_RUNS_DIR"]))

    def _run_id(store):
        from tests.helpers import only_run_id

        return only_run_id(store)

    def _planning_ready(store):
        from tests.integration.e2e_helpers import planning_single_leaf_script

        return planning_single_leaf_script(store)

    def _approve_plan(store):
        from tests.helpers import (
            done_events,
            mandatory_initial_respond_request,
            mandatory_scope_review_respond_request,
            respond_review,
        )
        from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW

        run_id = _run_id(store)
        reviews = [
            review for review in store.list_reviews(run_id) if review.get("type") == "whole_plan"
        ]
        loop = reviews[0] if reviews else {}
        stage = str(loop.get("active_stage") or "")
        loop_id = str(loop.get("id") or "review-whole-plan-01")

        def mutate() -> None:
            revision = int(store.load_plan(run_id)["revision"])
            if stage == "scope_review":
                request = mandatory_scope_review_respond_request(
                    store,
                    run_id,
                    loop_id=loop_id,
                    target_revision=revision,
                    review_type="whole_plan",
                )
            else:
                request = mandatory_initial_respond_request(
                    store,
                    run_id,
                    loop_id=loop_id,
                    target_revision=revision,
                    review_type="whole_plan",
                )
            respond_review(
                store,
                run_id,
                request,
                phase=WHOLE_PLAN_REVIEW,
                loop_id=loop_id,
            )()

        text = "blocker review turn" if stage == "scope_review" else "review turn"
        return done_events(text=text), mutate

    def _produce(store):
        from tests.integration.e2e_helpers import production_batch_script, root_child_item_ids

        run_id = _run_id(store)
        leaf_id = root_child_item_ids(store, run_id)[0]
        return production_batch_script(
            store,
            run_id,
            plan_items=[leaf_id],
            dispositions={leaf_id: {"disposition": "completed"}},
            submit_completion=True,
        )

    def _approve_output(store):
        from tests.helpers import (
            done_events,
            mandatory_initial_respond_request,
            mandatory_scope_review_respond_request,
            respond_review,
        )
        from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW

        run_id = _run_id(store)
        reviews = [
            review
            for review in store.list_reviews(run_id)
            if str(review.get("type") or "") == "whole_output"
        ]
        loop = reviews[0] if reviews else {}
        stage = str(loop.get("active_stage") or "")
        production = store.load_production(run_id)
        target_revision = int(production["output_revision"])
        loop_id = str(loop.get("id") or "review-whole-output-01")
        if stage != "scope_review":
            def mutate() -> None:
                respond_review(
                    store,
                    run_id,
                    mandatory_initial_respond_request(
                        store,
                        run_id,
                        loop_id=loop_id,
                        target_revision=target_revision,
                        review_type="whole_output",
                    ),
                    phase=WHOLE_OUTPUT_REVIEW,
                    loop_id=loop_id,
                )()

            return done_events(text="review turn"), mutate

        def scope_mutate() -> None:
            respond_review(
                store,
                run_id,
                mandatory_scope_review_respond_request(
                    store,
                    run_id,
                    loop_id=loop_id,
                    target_revision=int(store.load_production(run_id)["output_revision"]),
                    review_type="whole_output",
                ),
                phase=WHOLE_OUTPUT_REVIEW,
                loop_id=loop_id,
            )()

        return done_events(text="blocker review turn"), scope_mutate

    def _finish_production(store):
        run = store.load_run(_run_id(store))
        phase = str(run.get("phase") or "")
        if phase == "production":
            return _produce(store)
        return _approve_output(store)

    def _resolve_script(self: StubProvider, session_id: str) -> list[dict[str, object]]:
        script = os.environ.get("TDP_SLICE10_SCRIPT") or ""
        if script == "block":
            ready = os.environ.get("TDP_STUB_TURN_READY_PATH")
            if ready:
                Path(ready).write_text("ready\n", encoding="utf-8")
            time.sleep(float(os.environ.get("TDP_STUB_TURN_BLOCK_SECONDS", "10")))
            return [{"type": "done", "subtype": "success", "text": "stub turn timed out"}]

        store = _store()
        if script == "plan":
            events, mutate = _planning_ready(store)
        elif script == "approve_plan":
            events, mutate = _approve_plan(store)
        elif script == "produce":
            events, mutate = _produce(store)
        elif script == "approve_output":
            events, mutate = _approve_output(store)
        elif script == "finish_production":
            events, mutate = _finish_production(store)
        else:
            raise RuntimeError(f"unknown TDP_SLICE10_SCRIPT={script!r}")
        self._sessions[session_id].pending_hook = mutate
        return events

    def _new_session_id(self: StubProvider) -> str:
        prefix = os.environ.get("TDP_SLICE10_SESSION_PREFIX") or _SCRIPT
        self._counter += 1
        return f"stub-session-{prefix}-{self._counter}-{uuid.uuid4().hex[:8]}"

    StubProvider._resolve_script = _resolve_script  # type: ignore[method-assign]
    StubProvider._new_session_id = _new_session_id  # type: ignore[method-assign]
