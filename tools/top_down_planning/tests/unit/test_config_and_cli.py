"""Unit tests for configuration resolution and CLI overrides."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from top_down_planning.config import (
    ConfigError,
    compute_input_digest,
    resolve_config,
)
from top_down_planning.persistence import compute_config_digest


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_yaml_cli_precedence_changes_resolved_values(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "base.yaml",
        """
version: 1
run:
  output_goal: Deliver from YAML.
planning:
  max_depth: 3
""",
    )

    base = resolve_config(config_path)
    overridden = resolve_config(
        config_path,
        ["planning.max_depth=5", "limits.production.max_batches=80"],
    )

    assert base["planning"]["max_depth"] == 3
    assert overridden["planning"]["max_depth"] == 5
    assert overridden["limits"]["production"]["max_batches"] == 80
    assert overridden["run"]["output_goal"] == "Deliver from YAML."


def test_override_digest_changes_when_cli_set_applied(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "base.yaml",
        "run:\n  output_goal: Goal.\nplanning:\n  max_depth: 4\n",
    )
    base = resolve_config(config_path)
    overridden = resolve_config(config_path, ["planning.max_depth=5"])

    assert compute_config_digest(base) != compute_config_digest(overridden)


def test_unknown_override_path_fails_explicitly(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(config_path, ["foo.bar=1"])


def test_override_values_parse_yaml_types(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    resolved = resolve_config(
        config_path,
        [
            "planning.max_depth=5",
            "review.whole_plan.required=false",
            "run.input_refs=[README.md, docs/spec.md]",
        ],
    )
    assert resolved["planning"]["max_depth"] == 5
    assert resolved["review"]["whole_plan"]["required"] is False
    assert resolved["run"]["input_refs"] == ["README.md", "docs/spec.md"]


def test_input_digest_uses_file_content_when_ref_exists(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    readme = config_dir / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config_path = _write_config(
        config_dir / "base.yaml",
        "run:\n  output_goal: Goal.\n  input_refs:\n    - README.md\n",
    )
    resolved = resolve_config(config_path)
    digest_once = compute_input_digest(resolved, base_dir=config_dir)

    readme.write_text("beta", encoding="utf-8")
    digest_twice = compute_input_digest(resolved, base_dir=config_dir)
    assert digest_once != digest_twice


def test_cli_run_persists_resolved_config_and_status_reads_run(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = _write_config(
        config_dir / "run.yaml",
        "run:\n  output_goal: Deliver the sample output.\n",
    )
    runs_dir = tmp_path / "runs"

    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "run",
            "--config",
            str(config_path),
            "--set",
            "planning.max_depth=5",
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 2, run_result.stderr
    run_payload = json.loads(run_result.stdout)
    run_id = run_payload["run_id"]

    status_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "status",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert status_result.returncode == 0, status_result.stderr
    status_payload = json.loads(status_result.stdout)
    assert status_payload["ok"] is True
    assert status_payload["run"]["phase"] == "planning"
    assert status_payload["run"]["plan_revision"] == 0

    resolved_path = runs_dir / run_id / "resolved-config.yaml"
    assert resolved_path.exists()
    assert "max_depth: 5" in resolved_path.read_text(encoding="utf-8")


def test_cli_unknown_set_override_exits_non_zero(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = _write_config(
        config_dir / "run.yaml",
        "run:\n  output_goal: Deliver the sample output.\n",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "run",
            "--config",
            str(config_path),
            "--set",
            "foo.bar=1",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"


def test_cli_validate_reports_plan_issues(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = _write_config(
        config_dir / "run.yaml",
        "run:\n  output_goal: Deliver the sample output.\n",
    )
    runs_dir = tmp_path / "runs"

    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    run_id = json.loads(run_result.stdout)["run_id"]

    plan_path = runs_dir / run_id / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    child = {
        "id": "item-child",
        "parent_id": "item-root",
        "order_key": "0000000000",
        "title": "Child",
        "outcome": "",
        "scope": {"includes": [], "excludes": []},
        "boundaries": [],
        "depends_on": ["item-missing"],
        "acceptance": [],
        "planning_status": "open",
    }
    plan["items"].append(child)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    validate_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "validate",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert validate_result.returncode == 1, validate_result.stderr
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "missing_dependency_target" in codes


def test_validate_uses_approval_mode_when_whole_plan_review_approved(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = _write_config(
        config_dir / "run.yaml",
        "run:\n  output_goal: Deliver the sample output.\nplanning:\n  max_depth: 2\n",
    )
    runs_dir = tmp_path / "runs"

    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    run_id = json.loads(run_result.stdout)["run_id"]
    reviews_dir = runs_dir / run_id / "reviews"
    (reviews_dir / "review-whole-plan-01.json").write_text(
        json.dumps(
            {
                "id": "review-whole-plan-01",
                "type": "whole_plan",
                "status": "approved",
                "target_revision": 0,
                "findings": [],
            }
        ),
        encoding="utf-8",
    )

    validate_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "top_down_planning.cli.main",
            "validate",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(validate_result.stdout)
    assert payload["mode"] == "approval"
