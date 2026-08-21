"""Slice 7 re-review: resume schema, binding paths, globs, ops errors, doctor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from top_down_planning.cli.execute import parse_upstream_bindings
from top_down_planning.config import (
    ConfigError,
    InvalidSnapshotBindingError,
    build_context_snapshot_payload,
    resolve_config,
    validate_context_snapshot_binding,
)
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import write_config
from tests.support.cli_fakes import _assert_operational_error, _minimal_run_yaml
from tests.support.run_builders import (
    _built_package,
    _create_planning_run,
    _pause_run,
    _wipe_txn_dirs,
)


def _assert_config_error(result, *, structured: bool) -> None:
    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
    if structured:
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "config_error"


@pytest.mark.parametrize(
    "override",
    [
        "runtime.runs_dir=2",
        "observability.show_agent_text=1",
        "planning.max_depth=not-an-int",
    ],
)
def test_resume_set_without_config_validates_resolved_schema(
    tmp_path: Path, override: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T101001-101001")
    _pause_run(store, run_id)
    argv = [
        "resume",
        "--run",
        run_id,
        "--runs-dir",
        str(store.root),
        "--set",
        override,
        "--check",
    ]
    _assert_config_error(run_cli([*argv, "--stream-json"]), structured=True)
    _assert_config_error(run_cli(argv), structured=False)


@pytest.mark.parametrize(
    "path_key",
    ["./foo", "foo/./bar", "foo//bar", "C:/foo"],
)
def test_snapshot_binding_rejects_noncanonical_path_keys(path_key: str) -> None:
    digest = "a" * 64
    with pytest.raises(InvalidSnapshotBindingError, match="canonical"):
        validate_context_snapshot_binding(
            {
                "resource_digests": {path_key: digest},
                "skill_digests": {},
                "guidance_digests": [],
            }
        )


@pytest.mark.parametrize(
    "path_key",
    ["./foo", "foo/./bar", "foo//bar", "C:/foo"],
)
def test_status_reports_corrupt_run_for_noncanonical_binding_keys(
    tmp_path: Path, path_key: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T101101-101101")
    run_path = store.run_dir(run_id) / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["context_snapshot_binding"]["resource_digests"] = {path_key: "a" * 64}
    run_path.write_text(json.dumps(payload), encoding="utf-8")
    _wipe_txn_dirs(store.run_dir(run_id))

    result = run_cli(
        ["status", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "corrupt_run"
    assert "Traceback" not in result.stderr


def test_resource_globs_require_workspace_containment(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "leak.md").write_text("secret\n", encoding="utf-8")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "ok.md").write_text("ok\n", encoding="utf-8")
    (workspace / "alias.md").symlink_to(outside / "leak.md")

    def _run(resource: str) -> None:
        cfg = write_config(
            tmp_path / "glob.yaml",
            _minimal_run_yaml(
                workspace,
                "agent_context:\n  roles:\n    producer:\n      resources:\n"
                f'        - "{resource}"\n',
            ),
        )
        human = run_cli(
            ["run", "--config", str(cfg), "--runs-dir", str(tmp_path / "runs")]
        )
        structured = run_cli(
            [
                "run",
                "--config",
                str(cfg),
                "--runs-dir",
                str(tmp_path / "runs"),
                "--stream-json",
            ]
        )
        _assert_config_error(human, structured=False)
        _assert_config_error(structured, structured=True)

    _run("../outside/*.md")
    (outside / "leak.md").unlink()
    _run("../outside/*.md")
    (outside / "leak.md").write_text("secret\n", encoding="utf-8")
    _run(str(outside / "*.md"))
    _run("*.md")


def test_guidance_read_oserror_is_operational(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    guide = workspace / "guide.md"
    guide.write_text("Be careful.\n", encoding="utf-8")
    cfg = write_config(
        tmp_path / "guide.yaml",
        _minimal_run_yaml(
            workspace,
            "agent_context:\n  roles:\n    producer:\n      guidance:\n"
            "        - file: guide.md\n",
        ),
    )
    original = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.name == "guide.md":
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    with patch.object(Path, "read_text", _read_text):
        human = run_cli(
            ["run", "--config", str(cfg), "--runs-dir", str(tmp_path / "runs")]
        )
        structured = run_cli(
            [
                "run",
                "--config",
                str(cfg),
                "--runs-dir",
                str(tmp_path / "runs"),
                "--stream-json",
            ]
        )
    _assert_operational_error(human, structured=False)
    _assert_operational_error(structured, structured=True)


def test_parse_upstream_rejects_trailing_run_id_whitespace() -> None:
    with pytest.raises(ValueError):
        parse_upstream_bindings(["item-a=run-20260101T000001-000001 "])


def test_execute_upstream_trailing_run_id_whitespace_is_usage_error(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--unit",
            "item-foundation",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--upstream",
            "item-foundation=run-20260101T000001-000001 ",
            "--stream-json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "sub_tdp_upstream_invalid"
    human = run_cli(
        [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--unit",
            "item-foundation",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--upstream",
            "item-foundation=run-20260101T000001-000001 ",
        ]
    )
    assert human.exit_code == 2
    assert "Traceback" not in human.stderr


def test_run_prepare_execute_normalize_store_root_oserror(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("file\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = write_config(tmp_path / "ops.yaml", _minimal_run_yaml(workspace))

    for command, extra in (
        (["run", "--config", str(cfg)], []),
        (["prepare", "--config", str(cfg), "--output", str(tmp_path / "pkg")], []),
    ):
        argv = [*command, "--runs-dir", str(blocked), *extra]
        _assert_operational_error(run_cli([*argv, "--stream-json"]), structured=True)
        _assert_operational_error(run_cli(argv), structured=False)

    _, _, package = _built_package(tmp_path)
    exec_argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(blocked),
    ]
    with patch(
        "top_down_planning.orchestrator.prepared_run_factory.validate_resolved_config_against_package"
    ):
        _assert_operational_error(run_cli([*exec_argv, "--stream-json"]), structured=True)
        _assert_operational_error(run_cli(exec_argv), structured=False)


def test_prepare_package_output_oserror_is_operational(tmp_path: Path) -> None:
    from types import SimpleNamespace

    cfg = write_config(
        tmp_path / "prep.yaml",
        """
run:
  output_goal: Goal.
provider:
  name: stub
""",
    )
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "pkg"
    continuation = SimpleNamespace(cancelled=False, reason=None)

    def _continue(run_id: str, until: str = "validated"):
        store = FileRunStore(runs_dir)
        run = store.load_run(run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["phase"] = PLAN_VALIDATED
        store.save_run(run_id, run, expected)
        return continuation

    engine = MagicMock()
    engine.continue_run.side_effect = _continue
    argv = [
        "prepare",
        "--config",
        str(cfg),
        "--runs-dir",
        str(runs_dir),
        "--output",
        str(output_dir),
    ]
    with (
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            side_effect=OSError("disk full"),
        ),
    ):
        _assert_operational_error(run_cli([*argv, "--stream-json"]), structured=True)
        _assert_operational_error(run_cli(argv), structured=False)


def test_workspace_doctor_reports_unreadable_and_invalid_run_json(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)

    malformed_id = "run-20260101T101201-101201"
    malformed_dir = store.root / malformed_id
    malformed_dir.mkdir()
    (malformed_dir / "run.json").write_text("{not-json", encoding="utf-8")

    utf8_id = "run-20260101T101202-101202"
    utf8_dir = store.root / utf8_id
    utf8_dir.mkdir()
    (utf8_dir / "run.json").write_bytes(b"\xff\xfe")

    semantic_id = "run-20260101T101203-101203"
    semantic_dir = store.root / semantic_id
    semantic_dir.mkdir()
    (semantic_dir / "run.json").write_text(
        json.dumps({"id": semantic_id, "status": "not-a-status"}),
        encoding="utf-8",
    )

    structured = run_cli(
        ["doctor", "--runs-dir", str(store.root), "--stream-json"]
    )
    human = run_cli(["doctor", "--runs-dir", str(store.root)])
    assert structured.exit_code == 1
    payload = json.loads(structured.stdout)
    assert payload["ok"] is False
    corrupt = payload["workspace"]["corrupt_run_dirs"]
    assert malformed_id in corrupt
    assert utf8_id in corrupt
    assert semantic_id in corrupt
    assert human.exit_code == 1
    assert malformed_id in human.stdout
    assert "corrupt run dirs" in human.stdout
    assert "Traceback" not in human.stderr
    assert "Traceback" not in structured.stderr


def test_valid_workspace_glob_builds_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "docs").mkdir()
    (workspace / "docs" / "ok.md").write_text("ok\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "ok.yaml",
            _minimal_run_yaml(
                workspace,
                "agent_context:\n  roles:\n    producer:\n      resources:\n"
                "        - docs/*.md\n",
            ),
        ),
        cwd=workspace,
    )
    binding = build_context_snapshot_payload(config, workspace=workspace)
    assert "docs/ok.md" in binding["resource_digests"]


def test_outside_glob_raises_config_error(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "leak.md").write_text("x\n", encoding="utf-8")
    config = resolve_config(
        write_config(
            tmp_path / "bad.yaml",
            _minimal_run_yaml(
                workspace,
                "agent_context:\n  roles:\n    producer:\n      resources:\n"
                '        - "../outside/*.md"\n',
            ),
        ),
        cwd=workspace,
    )
    with pytest.raises(ConfigError):
        build_context_snapshot_payload(config, workspace=workspace)
