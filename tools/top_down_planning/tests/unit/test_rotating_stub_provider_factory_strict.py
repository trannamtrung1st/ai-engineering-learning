"""Strict RotatingStubProviderFactory scheduling regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.provider import StubProvider
from top_down_planning.persistence import FileRunStore
from top_down_planning.domain.models import Plan, PlanItem
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config, plan_root_item
from tests.support.stub_provider_factory import RotatingStubProviderFactory


def test_strict_factory_rejects_unexpected_role_before_consuming_script(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020101-020101"
    root = plan_root_item(title="Root", outcome="Root outcome.")
    store.create_run(
        run_id,
        plan=Plan(
            id=f"plan-{run_id}",
            revision=0,
            output_goal="Goal.",
            items={"item-root": root},
        ),
        **create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config()),
    )
    factory = RotatingStubProviderFactory(
        store,
        run_id,
        strict_session_scripts=True,
    )
    factory.script_turn(
        done_events(text="reviewer turn"),
        expected_role="reviewer",
        expected_kind="reviewer",
    )
    provider = factory.create_provider({}, tmp_path)

    with pytest.raises(AssertionError, match="unexpected provider role"):
        provider.start_primary_session(
            "producer",
            {"run_id": run_id, "phase": "planning"},
        )

    assert factory._shared_index == 0  # noqa: SLF001 — harness contract
