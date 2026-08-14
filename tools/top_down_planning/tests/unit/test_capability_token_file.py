"""Capability token file authorization."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.provider import StubProvider
from top_down_planning.agent_tool.authorization import authorize_mutation, resolve_capability_token
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    rebind_primary_session_capability,
    revoke_capabilities_for_phase,
)
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.session_events import sync_persisted_session_id
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import (
    CAPABILITY_TOKEN_FILE_ENV_VAR,
    capability_token_file_path,
    write_capability_token_file,
)
from tests.helpers import create_run_kwargs, grant_capability, minimal_resolved_config


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T006001-006001") -> None:
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def test_resolve_capability_token_reads_token_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_path = write_capability_token_file(store, run_id, token)

    monkeypatch.setenv(CAPABILITY_TOKEN_FILE_ENV_VAR, str(token_path))

    assert resolve_capability_token() == token


def test_authorize_mutation_uses_token_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_path = write_capability_token_file(store, run_id, token)

    monkeypatch.setenv(CAPABILITY_TOKEN_FILE_ENV_VAR, str(token_path))

    role = authorize_mutation(store, run_id, operation="plan_apply")
    assert role == "planner"


def test_revoked_token_file_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    store.revoke_capability(run_id, token_id)
    token_path = write_capability_token_file(store, run_id, token)
    monkeypatch.setenv(CAPABILITY_TOKEN_FILE_ENV_VAR, str(token_path))

    with pytest.raises(CapabilityDeniedError, match="revoked"):
        authorize_mutation(store, run_id, operation="plan_apply")

    replacement = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_path = write_capability_token_file(store, run_id, replacement)
    monkeypatch.setenv(CAPABILITY_TOKEN_FILE_ENV_VAR, str(token_path))
    authorize_mutation(store, run_id, operation="plan_apply")


def test_bind_provider_capability_writes_token_file(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    provider = StubProvider()
    token = grant_capability(
        store,
        run_id,
        role="planner",
        phase=PLANNING,
        session_id="stub-session-planner",
    )

    bind_provider_capability(provider, token, store=store, run_id=run_id)

    token_path = capability_token_file_path(store, run_id)
    assert token_path.read_text(encoding="utf-8").strip() == token
    assert provider._capability_token == token
    assert provider._capability_token_file == str(token_path)


def test_sync_persisted_session_id_rebinds_capability_for_durable_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    provider = StubProvider()
    pending_token = grant_capability(
        store,
        run_id,
        role="planner",
        phase=PLANNING,
        session_id="cursor-pending-1",
    )
    bind_provider_capability(provider, pending_token, store=store, run_id=run_id)

    durable_id = "durable-planner-session-01"
    provider._ensure_durable_session(durable_id, role="planner", kind="primary")
    resolved = sync_persisted_session_id(
        provider,
        store,
        run_id,
        durable_id,
        role="planner",
    )

    assert resolved == durable_id
    token_path = capability_token_file_path(store, run_id)
    file_token = token_path.read_text(encoding="utf-8").strip()
    assert file_token != pending_token
    authorize_mutation(store, run_id, operation="plan_apply", capability_token=file_token)


def test_revoke_capabilities_for_phase_clears_token_file(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    write_capability_token_file(store, run_id, token)

    revoke_capabilities_for_phase(store, run_id, PLANNING)

    assert not capability_token_file_path(store, run_id).exists()


def test_rebind_primary_session_capability_updates_token_file(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store)
    provider = StubProvider()
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id="durable-planner-session-01",
        provider="cursor",
    )

    token = rebind_primary_session_capability(
        store,
        run_id,
        provider,
        role="planner",
    )

    assert token is not None
    assert capability_token_file_path(store, run_id).read_text(encoding="utf-8").strip() == token
    authorize_mutation(store, run_id, operation="plan_apply", capability_token=token)
