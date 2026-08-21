"""CLI assertion and engine-patch helpers shared by Slice 7 regressions."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.persistence import FileRunStore


def _stdout_json(result) -> dict:
    return json.loads(result.stdout)


def _assert_no_traceback(result) -> None:
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def _assert_structured_error(result, code: str) -> None:
    _assert_no_traceback(result)
    assert result.exit_code != 0
    payload = _stdout_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def _resume_check_argv(run_id: str, runs_dir: Path) -> list[str]:
    return ["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--check"]


def _assert_operational_without_traceback(result) -> None:
    assert result.exit_code == 1
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr
    if str(getattr(result, "stdout", "") or "").strip().startswith("{"):
        payload = _stdout_json(result)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "operational_error"


def _assert_operational_error(result, *, structured: bool) -> None:
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
    if structured:
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "operational_error"


def _minimal_run_yaml(workspace: Path, extra: str = "") -> str:
    return (
        "run:\n  output_goal: Goal.\n"
        f"project:\n  workspace: {workspace}\n"
        "provider:\n  name: stub\n"
        f"{extra}"
    )


def _engine_patches(tmp_path: Path):
    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=True,
        run_id="run-placeholder",
        phase="planning",
        status="running",
        outcome=None,
        reason=None,
        cancelled=False,
        target_reached=True,
    )
    return [
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            return_value=SimpleNamespace(
                package_id="pkg-x",
                manifest_path=tmp_path / "pkg" / "manifest.json",
                manifest={
                    "planning_run": {
                        "approved_plan_revision": 0,
                        "approved_plan_digest": "a" * 64,
                    }
                },
            ),
        ),
    ]


@contextmanager
def _patch_prepare_plan_validated():
    real_load = FileRunStore.load_run
    real_snapshot = FileRunStore.load_canonical_snapshot

    def load_as_validated(self, rid, *args, **kwargs):
        run = dict(real_load(self, rid, *args, **kwargs))
        run["phase"] = "plan_validated"
        return run

    def snapshot_as_validated(self, rid, *args, **kwargs):
        snapshot = real_snapshot(self, rid, *args, **kwargs)
        run = dict(snapshot.run)
        run["phase"] = "plan_validated"
        return replace(snapshot, run=run)

    with (
        patch.object(FileRunStore, "load_run", load_as_validated),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_as_validated),
    ):
        yield
