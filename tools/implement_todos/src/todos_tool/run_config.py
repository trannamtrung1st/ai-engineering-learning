"""Run configuration for the todos orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_COMMIT_HINT = """\
When your decision is `pass`, include `proposed_commit_message` in the JSON with the
exact full commit subject the orchestrator should use.

Format:
- Start with `agent:` as the provenance prefix
- Follow with the conventional type for the item (`feat:` for feature, `fix:` for fix,
  `refactor:` for refactor)
- End with a concise imperative subject describing the actual repository change

Example: `agent: feat: add account registration`
""".strip()


@dataclass
class RunConfig:
    workspace_root: Path
    todos_dir: str = "todos"
    allow_dirty: bool = True
    no_color: bool = False
    model: str | None = None
    stop_on_failure: bool | None = None
    auto_commit: bool | None = None
    agent_bin: str | None = None
    skip_probe: bool = False
    dry_run_prompts: bool = False
    dry_run: bool = False
    project_config: Path | None = None
    context_files: tuple[str, ...] = ()
    skip_commit: bool = False
    no_auto_repair_yaml: bool = False
    max_yaml_repair_attempts: int = 2
    commit_hint: str = field(default_factory=lambda: DEFAULT_COMMIT_HINT)
    evidence_mode: str | None = None
    max_identical_evidence_failures: int = 3
    evidence_batch_timeout_seconds: int | None = None
