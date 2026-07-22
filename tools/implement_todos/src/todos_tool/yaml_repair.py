"""Bounded YAML auto-repair for malformed TODO-set documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.cursor_client import CursorClient
from todos_tool.errors import TodosToolError, ValidationError
from todos_tool.git_service import status
from todos_tool.manifest import Workspace, load_workspace
from todos_tool.persistence import write_json
from todos_tool.profile_loader import ResolvedContextFile
from todos_tool.project_context import ProjectContext
from todos_tool.prompts import build_repair_prompt


class Recoverability(str, Enum):
    REPAIRABLE = "repairable"
    NOT_REPAIRABLE = "not_repairable"


def classify_validation_error(exc: ValidationError) -> Recoverability:
    """Return whether a manifest load ValidationError may be auto-repaired."""
    for err in exc.errors:
        lower = err.lower()
        if "todos directory not found" in lower:
            return Recoverability.NOT_REPAIRABLE
        if "missing manifest" in lower:
            return Recoverability.NOT_REPAIRABLE
        if "manifest.yaml has no items" in lower:
            return Recoverability.NOT_REPAIRABLE
        if "manifest version must be" in lower:
            return Recoverability.NOT_REPAIRABLE
        if "unsupported schema" in lower:
            return Recoverability.NOT_REPAIRABLE
        if "unsupported profile" in lower:
            return Recoverability.NOT_REPAIRABLE
    return Recoverability.REPAIRABLE


def discover_todo_yaml_files(repo_root: Path, todos_dir_name: str) -> list[str]:
    """Return repository-relative paths to candidate TODO YAML files."""
    todos_dir = repo_root / todos_dir_name
    if not todos_dir.is_dir():
        return []

    rel_paths: set[str] = set()
    manifest = todos_dir / "manifest.yaml"
    if manifest.is_file():
        rel_paths.add(f"{todos_dir_name}/manifest.yaml")

    for path in sorted(todos_dir.rglob("*.yaml")):
        rel = path.relative_to(repo_root).as_posix()
        if f"{todos_dir_name}/runs/" in rel:
            continue
        if path.name == "manifest.yaml":
            continue
        rel_paths.add(rel)
    for path in sorted(todos_dir.rglob("*.yml")):
        rel = path.relative_to(repo_root).as_posix()
        if f"{todos_dir_name}/runs/" in rel:
            continue
        rel_paths.add(rel)
    return sorted(rel_paths)


def todo_yaml_content_hash(repo_root: Path, todos_dir_name: str) -> str:
    """Hash TODO YAML contents for no-progress detection."""
    digest = hashlib.sha256()
    for rel in discover_todo_yaml_files(repo_root, todos_dir_name):
        path = repo_root / rel
        if not path.is_file():
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0missing\0")
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _authoring_guide_path() -> str | None:
    guide = Path(__file__).resolve().parents[2] / "README.md"
    return str(guide) if guide.is_file() else None


@dataclass
class RepairAttemptRecord:
    attempt: int
    diagnostic: str
    content_hash: str
    changed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    session_log: str | None = None


@dataclass
class YamlRepairLog:
    started_at: str
    todos_dir: str
    initial_diagnostic: str
    attempts: list[RepairAttemptRecord] = field(default_factory=list)
    success: bool = False
    final_diagnostic: str | None = None

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "todos_dir": self.todos_dir,
            "initial_diagnostic": self.initial_diagnostic,
            "success": self.success,
            "final_diagnostic": self.final_diagnostic,
            "attempts": [
                {
                    "attempt": entry.attempt,
                    "diagnostic": entry.diagnostic,
                    "content_hash": entry.content_hash,
                    "changed_paths": list(entry.changed_paths),
                    "forbidden_paths": list(entry.forbidden_paths),
                    "session_log": entry.session_log,
                }
                for entry in self.attempts
            ],
        }


class YamlRepairCoordinator:
    """Run bounded Cursor repair sessions for malformed TODO YAML."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        todos_dir: str,
        client: CursorClient,
        project_context: ProjectContext,
        resolved_context_files: list[ResolvedContextFile],
        renderer: ConsoleRenderer,
        max_attempts: int = 2,
        repair_log_dir: Path | None = None,
        set_name: str = "todos",
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.todos_dir = todos_dir
        self.client = client
        self.project_context = project_context
        self.resolved_context_files = resolved_context_files
        self.renderer = renderer
        self.max_attempts = max(0, max_attempts)
        self.repair_log_dir = repair_log_dir or (
            self.workspace_root / todos_dir / "runs" / "_yaml-repair"
        )
        self.set_name = set_name
        self.repair_log_dir.mkdir(parents=True, exist_ok=True)

    async def repair(self, exc: ValidationError) -> Workspace:
        if classify_validation_error(exc) != Recoverability.REPAIRABLE:
            raise exc
        if self.max_attempts <= 0:
            raise exc

        log = YamlRepairLog(
            started_at=datetime.now(timezone.utc).isoformat(),
            todos_dir=self.todos_dir,
            initial_diagnostic=str(exc),
        )
        log_path = self.repair_log_dir / "repair-log.json"

        diagnostic = str(exc)
        prev_hash = todo_yaml_content_hash(self.workspace_root, self.todos_dir)
        prev_diagnostic = diagnostic
        allowed = set(discover_todo_yaml_files(self.workspace_root, self.todos_dir))

        for attempt in range(1, self.max_attempts + 1):
            prompt = build_repair_prompt(
                diagnostic=diagnostic,
                todos_dir=self.todos_dir,
                yaml_files=discover_todo_yaml_files(
                    self.workspace_root,
                    self.todos_dir,
                ),
                project_context=self.project_context,
                resolved_context_files=self.resolved_context_files,
                authoring_guide_path=_authoring_guide_path(),
            )
            attempt_dir = self.repair_log_dir / f"attempt-{attempt:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = attempt_dir / "repair-prompt.md"
            prompt_path.write_text(prompt, encoding="utf-8")
            events_path = attempt_dir / "repair-session.ndjson"
            session_log = attempt_dir / "repair-session.log"

            before_paths = set(status(self.workspace_root).changed_paths)
            self.renderer.rule(
                f"YAML REPAIR attempt={attempt}/{self.max_attempts}"
            )
            session_renderer = ConsoleRenderer.with_file_logging(
                self.renderer,
                session_log,
            )
            await self.client.run_session(
                workspace=self.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                phase="repair",
                timeout_seconds=900,
                events_path=events_path,
                log_path=session_log,
                renderer=session_renderer,
            )

            after_paths = set(status(self.workspace_root).changed_paths)
            repair_touched = sorted(after_paths - before_paths)
            forbidden = sorted(path for path in repair_touched if path not in allowed)
            content_hash = todo_yaml_content_hash(self.workspace_root, self.todos_dir)

            record = RepairAttemptRecord(
                attempt=attempt,
                diagnostic=diagnostic,
                content_hash=content_hash,
                changed_paths=repair_touched,
                forbidden_paths=forbidden,
                session_log=str(session_log),
            )
            log.attempts.append(record)
            write_json(log_path, log.to_dict())

            if forbidden:
                message = (
                    "YAML repair changed paths outside TODO YAML: "
                    + ", ".join(forbidden)
                )
                log.final_diagnostic = message
                write_json(log_path, log.to_dict())
                raise TodosToolError(f"{message}\nRepair log: {log_path}")

            try:
                workspace = load_workspace(self.workspace_root, self.todos_dir)
            except ValidationError as reload_exc:
                diagnostic = str(reload_exc)
                if (
                    content_hash == prev_hash
                    and diagnostic == prev_diagnostic
                ):
                    log.final_diagnostic = diagnostic
                    write_json(log_path, log.to_dict())
                    break
                prev_hash = content_hash
                prev_diagnostic = diagnostic
                continue

            log.success = True
            write_json(log_path, log.to_dict())
            self.renderer.info(
                f"YAML repair succeeded after attempt {attempt} "
                f"(log: {log_path})"
            )
            return workspace

        log.final_diagnostic = diagnostic
        write_json(log_path, log.to_dict())
        raise TodosToolError(
            f"YAML repair exhausted after {self.max_attempts} attempt(s):\n"
            f"{diagnostic}\nRepair log: {log_path}"
        )
