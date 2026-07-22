"""Schedule, execute, review, commit, and resume TODO items."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.continuation import (
    apply_restructure_proposal,
    build_continuation_context,
    load_restructure_proposal,
)
from todos_tool.cursor_client import CursorClient, SessionResult
from todos_tool.errors import (
    CursorEnvironmentError,
    CursorSessionError,
    GitError,
    ReviewError,
    RestructuringError,
    SchedulingError,
    TodosToolError,
    UserInterrupted,
)
from todos_tool.git_finalize import finalize_worktree
from todos_tool.git_service import (
    ensure_git_repo,
    head_sha,
    paths_changed_since,
    status,
    verify_commit_sha,
    verify_pre_dirty_unchanged,
)
from todos_tool.manifest import Workspace, save_item
from todos_tool.model_config import resolve_model
from todos_tool.models import (
    CommitState,
    ItemStatus,
    Phase,
    RunState,
    TodoItem,
    Transition,
)
from todos_tool.persistence import (
    attempts_dir,
    load_state,
    new_run_state,
    record_transition,
    save_state,
    state_path,
    write_json,
)
from todos_tool.profile_loader import (
    load_project_context,
    resolve_context_files,
    validate_required_context,
)
from todos_tool.project_context import ProjectContext
from todos_tool.prompts import build_review_prompt, build_work_prompt
from todos_tool.reviewer import accept_decision, parse_review_decision
from todos_tool.review_context import build_review_context
from todos_tool.run_config import RunConfig
from todos_tool.scheduler import list_ready, next_ready
from todos_tool.validation_runner import (
    format_validation_results,
    resolve_validation_commands,
    run_validation_commands,
)
from todos_tool.workspace_loader import load_workspace_repairable


__all__ = ["Orchestrator", "RunConfig", "RunReport"]


@dataclass
class RunReport:
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    retryable: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.renderer = ConsoleRenderer(no_color=config.no_color)
        self.project_context = load_project_context(
            config.workspace_root,
            profile_path=config.project_config,
            extra_context_files=config.context_files,
        )
        self.resolved_context_files = resolve_context_files(
            config.workspace_root,
            self.project_context.context_files,
        )
        self.workspace: Workspace | None = None
        self._client: CursorClient | None = None
        self._pre_dirty_fingerprints: dict[str, str] = {}

    @property
    def client(self) -> CursorClient:
        if self._client is None:
            manifest_model = None
            if self.workspace is not None:
                manifest_model = self.workspace.manifest.settings.model
            self._client = CursorClient(
                agent_bin=self.config.agent_bin,
                model=resolve_model(
                    self.config.model,
                    manifest_model=manifest_model,
                    workspace_loaded=self.workspace is not None,
                ),
                no_color=self.config.no_color,
                skip_probe=self.config.skip_probe,
                parse_error_threshold=(
                    self.workspace.manifest.settings.parse_error_threshold
                    if self.workspace is not None
                    else 20
                ),
            )
        return self._client

    def _resolve_auto_commit(self) -> bool:
        if self.workspace is None:
            return _resolve_auto_commit(
                cli_auto_commit=self.config.auto_commit,
                manifest_auto_commit=None,
            )
        return _resolve_auto_commit(
            cli_auto_commit=self.config.auto_commit,
            manifest_auto_commit=self.workspace.manifest.settings.auto_commit,
        )

    async def _ensure_workspace(self, *, allow_repair: bool | None = None) -> Workspace:
        if self.workspace is not None and allow_repair is False:
            return self.workspace
        repair = (
            not self.config.no_auto_repair_yaml
            if allow_repair is None
            else allow_repair
        )
        self.workspace = await load_workspace_repairable(
            self.config,
            allow_repair=repair,
            client=self.client if repair else None,
            project_context=self.project_context,
            resolved_context_files=self.resolved_context_files,
            renderer=self.renderer,
        )
        return self.workspace

    async def _reload_workspace(self) -> None:
        self.workspace = await load_workspace_repairable(
            self.config,
            allow_repair=not self.config.no_auto_repair_yaml,
            client=self.client,
            project_context=self.project_context,
            resolved_context_files=self.resolved_context_files,
            renderer=self.renderer,
        )

    def _manifest_out_of_scope(self) -> str | None:
        if self.workspace is None or not self.workspace.manifest.out_of_scope:
            return None
        return "\n".join(self.workspace.manifest.out_of_scope)

    def _checklist_payload(self, item: TodoItem) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in item.checklist]

    def _prompt_kwargs(self, item: TodoItem) -> dict[str, Any]:
        manifest = self.workspace.manifest if self.workspace else None
        return {
            "project_context": self.project_context,
            "resolved_context_files": self.resolved_context_files,
            "authority": manifest.authority if manifest else None,
            "hard_rules": manifest.hard_rules if manifest else None,
            "stop_conditions": manifest.stop_conditions if manifest else None,
            "out_of_scope": self._manifest_out_of_scope(),
            "contract_refs": item.contract_refs,
            "checklist": self._checklist_payload(item),
        }

    async def run(self, todo_id: str | None = None) -> RunReport:
        ensure_git_repo(self.config.workspace_root)
        await self._ensure_workspace()
        self._ensure_no_active_execution_for_run(todo_id)

        if self.config.dry_run_prompts:
            return await self._write_dry_run_prompts(todo_id)

        validate_required_context(self.resolved_context_files)

        settings = self.workspace.manifest.settings
        stop_on_failure = (
            self.config.stop_on_failure
            if self.config.stop_on_failure is not None
            else settings.stop_on_failure
        )
        report = RunReport()

        while True:
            try:
                item = next_ready(self.workspace, todo_id)
            except SchedulingError as exc:
                if todo_id is not None:
                    raise
                break

            outcome = "completed"
            try:
                await self._execute_item(item)
            except (CursorEnvironmentError, UserInterrupted):
                raise
            except TodosToolError as exc:
                self.renderer.error(f"{item.id}: {exc}")
                report.errors[item.id] = str(exc)
                outcome = _classify_item_outcome(self.workspace.get(item.id))
            else:
                refreshed = self.workspace.get(item.id)
                if refreshed and refreshed.status == ItemStatus.SUPERSEDED:
                    outcome = "skipped"

            _apply_outcome(report, item.id, outcome)

            if todo_id is not None:
                break
            if outcome in {"failed", "retryable", "blocked"} and stop_on_failure:
                break
            if outcome in {"failed", "retryable"}:
                break

            await self._reload_workspace()

            if todo_id is not None:
                break

        return report

    async def commit_item(self, item_id: str) -> str:
        """Commit trackable changes for a done item that has no commit SHA yet."""
        ensure_git_repo(self.config.workspace_root)
        await self._ensure_workspace(allow_repair=False)

        if not self._resolve_auto_commit():
            raise TodosToolError(
                "auto_commit is disabled; enable it in manifest or pass --auto-commit true"
            )

        item = self.workspace.get(item_id)
        if item is None:
            raise SchedulingError(f"Unknown item id: {item_id}")
        if item.status != ItemStatus.DONE:
            raise TodosToolError(
                f"{item_id} must be done before commit (status={item.status.value})"
            )
        if item.result.commit_sha:
            raise TodosToolError(
                f"{item_id} already committed as {item.result.commit_sha[:8]}"
            )

        runs_dir = self.workspace.runs_dir(item.id)
        state = load_state(runs_dir)
        if state is None:
            state = new_run_state(item.id, head_sha(self.config.workspace_root))
            state.work_summary = item.result.summary
        elif state.commit_state == CommitState.COMPLETED and state.commit_sha:
            verify_commit_sha(self.config.workspace_root, state.commit_sha)
            self._finalize_item_done(item, state.commit_sha, item.result.summary or "")
            return state.commit_sha

        await self._commit_item(item, state, runs_dir)
        sha = state.commit_sha or item.result.commit_sha
        if not sha:
            raise GitError(f"{item_id}: commit finished without a SHA")
        return sha

    async def resume(self) -> RunReport:
        """Resume any in_progress item from persisted state + git reality."""
        ensure_git_repo(self.config.workspace_root)
        await self._ensure_workspace()

        in_progress = [
            i for i in self.workspace.items if i.status == ItemStatus.IN_PROGRESS
        ]
        if not in_progress:
            for item in self.workspace.items:
                state = load_state(self.workspace.runs_dir(item.id))
                if state and state.phase != Phase.IDLE and item.status == ItemStatus.PENDING:
                    in_progress.append(item)
                    break

        resume_state: RunState | None = None
        if in_progress:
            item = in_progress[0]
            runs_dir = self.workspace.runs_dir(item.id)
            state = load_state(runs_dir)
            resume_state = state
            if state is not None:
                self._pre_dirty_fingerprints = _load_legacy_pre_dirty_fingerprints(
                    runs_dir
                )
                if self._pre_dirty_fingerprints:
                    verify_pre_dirty_unchanged(
                        self.config.workspace_root,
                        self._pre_dirty_fingerprints,
                        item_id=item.id,
                    )

        if in_progress:
            item = in_progress[0]
            runs_dir = self.workspace.runs_dir(item.id)
            prior = resume_state
            if prior and prior.agent_pid:
                if _pid_alive(prior.agent_pid):
                    raise TodosToolError(
                        f"Cannot resume {item.id}: Cursor agent still running "
                        f"(pid={prior.agent_pid}). Stop it manually, then resume."
                    )
                if not self.config.dry_run_prompts:
                    prior.agent_pid = None
                    save_state(runs_dir, prior)

        if self.config.dry_run_prompts:
            target = in_progress[0].id if in_progress else None
            return await self._write_dry_run_prompts(target, resume_state)

        if not in_progress:
            self.renderer.info("Nothing to resume; starting normal run")
            return await self.run()

        validate_required_context(self.resolved_context_files)

        item = in_progress[0]
        self.renderer.info(f"Resuming {item.id}")
        runs_dir = self.workspace.runs_dir(item.id)
        report = RunReport()
        outcome = "completed"
        try:
            await self._execute_item(item, resuming=True)
        except (CursorEnvironmentError, UserInterrupted):
            raise
        except TodosToolError as exc:
            self.renderer.error(f"{item.id}: {exc}")
            report.errors[item.id] = str(exc)
            outcome = _classify_item_outcome(self.workspace.get(item.id))
        else:
            refreshed = self.workspace.get(item.id)
            if refreshed and refreshed.status == ItemStatus.SUPERSEDED:
                outcome = "skipped"
        _apply_outcome(report, item.id, outcome)
        return report

    async def _execute_item(self, item: TodoItem, *, resuming: bool = False) -> None:
        settings = self.workspace.manifest.settings
        runs_dir = self.workspace.runs_dir(item.id)
        state = load_state(runs_dir)

        if state and state.commit_state == CommitState.COMPLETED and state.commit_sha:
            verify_commit_sha(self.config.workspace_root, state.commit_sha)
            self._finalize_item_done(item, state.commit_sha, state.work_summary or "")
            return

        if state is None:
            baseline = head_sha(self.config.workspace_root)
            state = new_run_state(item.id, baseline)
            save_state(runs_dir, state)
        elif resuming and self._pre_dirty_fingerprints:
            verify_pre_dirty_unchanged(
                self.config.workspace_root,
                self._pre_dirty_fingerprints,
                item_id=item.id,
            )

        if item.status == ItemStatus.PENDING:
            item.status = ItemStatus.IN_PROGRESS
            self._persist_item(item)

        feedback: str | None = state.review.summary
        if state.review.issues:
            feedback = (feedback or "") + "\nIssues:\n" + "\n".join(
                f"- {i}" for i in state.review.issues
            )

        if state.phase == Phase.COMMIT and state.commit_state in (
            CommitState.STARTED,
            CommitState.FAILED,
        ):
            await self._commit_item(item, state, runs_dir)
            return

        if (
            resuming
            and state.phase == Phase.WORK
            and state.last_transition
            in (
                Transition.WORK_PHASE_READY,
                Transition.VALIDATION_STARTED,
                Transition.VALIDATION_FAILED,
                Transition.VALIDATION_PASSED,
            )
        ):
            await self._reload_workspace()
            self._maybe_apply_restructure(item, runs_dir)
            item = self.workspace.get(item.id) or item
            if item.status == ItemStatus.SUPERSEDED:
                self.renderer.info(f"{item.id} superseded; stopping item")
                return
            review_outcome = await self._work_validate_review_attempt(
                item,
                state,
                runs_dir,
                feedback,
                preserve_session=True,
            )
            if review_outcome == "superseded":
                return
            await self._handle_review_outcome(
                item, state, runs_dir, review_outcome, feedback
            )
            return

        if (
            resuming
            and state.phase == Phase.WORK
            and state.last_transition
            in (
                Transition.WORK_SESSION_STARTED,
                Transition.WORK_SESSION_RESTARTED,
                Transition.WORK_PHASE_FAILED,
            )
        ):
            work_ok = await self._run_work_phase(
                item, state, runs_dir, feedback, preserve_session=True
            )
            if not work_ok:
                raise TodosToolError(state.review.summary or "Work phase failed")
            await self._reload_workspace()
            self._maybe_apply_restructure(item, runs_dir)
            item = self.workspace.get(item.id) or item
            if item.status == ItemStatus.SUPERSEDED:
                self.renderer.info(f"{item.id} superseded; stopping item")
                return
            review_outcome = await self._work_validate_review_attempt(
                item,
                state,
                runs_dir,
                feedback,
                preserve_session=True,
            )
            if review_outcome == "superseded":
                return
            await self._handle_review_outcome(
                item, state, runs_dir, review_outcome, feedback
            )
            return
        if (
            resuming
            and state.phase == Phase.REVIEW
            and state.last_transition
            in (Transition.REVIEW_SESSION_STARTED, Transition.REVIEW_SESSION_RESTARTED)
        ):
            review_outcome = await self._run_review_phase(
                item, state, runs_dir, feedback, preserve_session=True
            )
            await self._handle_review_outcome(
                item, state, runs_dir, review_outcome, feedback
            )
            return

        start_attempt = state.logical_attempt or 1
        if state.logical_attempt == 0:
            start_attempt = 1

        if state.last_transition in (
            Transition.REVIEW_FAILED,
            Transition.VALIDATION_FAILED,
        ):
            start_attempt = state.logical_attempt + 1
            feedback = self._attempt_failure_feedback(state)

        for attempt in range(start_attempt, settings.max_attempts + 1):
            state.logical_attempt = attempt
            state.session_number = 0
            state.session_restart_count = 0
            state.validation_attempt = 0
            state.validation_results = []
            state.validation_repair_count = 0
            state.phase = Phase.WORK
            state.commit_state = CommitState.NONE
            record_transition(runs_dir, state, Transition.ATTEMPT_STARTED)

            work_ok = await self._run_work_phase(item, state, runs_dir, feedback)
            if not work_ok:
                continue

            await self._reload_workspace()
            self._maybe_apply_restructure(item, runs_dir)
            item = self.workspace.get(item.id) or item
            if item.status == ItemStatus.SUPERSEDED:
                self.renderer.info(f"{item.id} superseded; stopping item")
                return

            review_outcome = await self._work_validate_review_attempt(
                item, state, runs_dir, feedback
            )
            if review_outcome == "superseded":
                self.renderer.info(f"{item.id} superseded; stopping item")
                return
            if review_outcome == "pass":
                await self._commit_item(item, state, runs_dir)
                return
            if review_outcome == "blocked":
                item = self.workspace.get(item.id) or item
                item.status = ItemStatus.BLOCKED
                self._persist_item(item)
                state.phase = Phase.IDLE
                record_transition(
                    runs_dir,
                    state,
                    Transition.ITEM_BLOCKED,
                    reason=state.blocked_reason,
                )
                raise TodosToolError(state.blocked_reason or "Item blocked by review")

            feedback = self._attempt_failure_feedback(state)

        item = self.workspace.get(item.id) or item
        item.status = ItemStatus.BLOCKED
        self._persist_item(item)
        state.blocked_reason = f"Exceeded {settings.max_attempts} logical attempts"
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)
        raise TodosToolError(state.blocked_reason)

    async def _handle_review_outcome(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
        review_outcome: str,
        feedback: str | None,
    ) -> None:
        if review_outcome == "pass":
            await self._commit_item(item, state, runs_dir)
            return
        if review_outcome == "blocked":
            item = self.workspace.get(item.id) or item
            item.status = ItemStatus.BLOCKED
            self._persist_item(item)
            state.phase = Phase.IDLE
            record_transition(
                runs_dir,
                state,
                Transition.ITEM_BLOCKED,
                reason=state.blocked_reason,
            )
            raise TodosToolError(state.blocked_reason or "Item blocked by review")
        raise TodosToolError(state.review.summary or "Review failed during resume")

    def _item_paths(self, state: RunState) -> list[str]:
        paths = paths_changed_since(
            self.config.workspace_root,
            state.baseline_head or "HEAD",
            set(),
        )
        return [
            path
            for path in paths
            if not path.startswith(f"{self.config.todos_dir}/runs/")
        ]

    async def _write_dry_run_prompts(
        self,
        todo_id: str | None,
        state: RunState | None = None,
    ) -> RunReport:
        await self._ensure_workspace(allow_repair=False)
        items = (
            [next_ready(self.workspace, todo_id)]
            if todo_id is not None
            else list_ready(self.workspace)
        )
        report = RunReport()
        for item in items:
            item_state = state if state and state.item_id == item.id else None
            logical_attempt = (
                item_state.logical_attempt
                if item_state and item_state.logical_attempt
                else 1
            )
            feedback = item_state.review.summary if item_state else None
            if item_state and item_state.review.issues:
                feedback = (feedback or "") + "\n" + "\n".join(
                    item_state.review.issues
                )
            item_paths = self._item_paths(item_state) if item_state else []
            validation = (
                item_state.validation_results
                if item_state
                and item_state.validation_attempt == logical_attempt
                else None
            )
            preview_dir = self.workspace.runs_dir(item.id) / "dry-run"
            preview_dir.mkdir(parents=True, exist_ok=True)
            prompt_kwargs = self._prompt_kwargs(item)
            work_prompt = build_work_prompt(
                item,
                logical_attempt=logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                todos_dir=self.config.todos_dir,
                previous_feedback=feedback,
                **prompt_kwargs,
            )
            review_ctx = (
                build_review_context(
                    self.config.workspace_root,
                    baseline_head=item_state.baseline_head if item_state else None,
                    paths=item_paths or None,
                )
                if item_state
                else None
            )
            review_prompt = build_review_prompt(
                item,
                logical_attempt=logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                work_summary=(
                    item_state.work_summary
                    if item_state and item_state.work_summary
                    else "(not executed in prompt-only dry run)"
                ),
                git_diff=(
                    review_ctx.format_summary()
                    if review_ctx
                    else "(not available before work executes)"
                ),
                git_status=(
                    review_ctx.status_porcelain
                    if review_ctx
                    else status(self.config.workspace_root).porcelain
                ),
                authoritative_validation=validation,
                prompt_only=validation is None,
                **prompt_kwargs,
            )
            (preview_dir / "work-prompt.md").write_text(
                work_prompt,
                encoding="utf-8",
            )
            (preview_dir / "review-prompt.md").write_text(
                review_prompt,
                encoding="utf-8",
            )
            report.planned.append(item.id)
        return report

    def _resolved_validation_commands(self, item: TodoItem) -> list[str]:
        return resolve_validation_commands(
            self.workspace.manifest,
            item,
            project_context=self.project_context,
        )

    def _invalidate_validation_cache(self, state: RunState) -> None:
        state.validation_attempt = 0
        state.validation_results = []

    def _validation_failure_feedback(self, state: RunState) -> str:
        return format_validation_results(state.validation_results)

    def _attempt_failure_feedback(self, state: RunState) -> str | None:
        if (
            state.last_transition == Transition.VALIDATION_FAILED
            and state.validation_results
        ):
            return self._validation_failure_feedback(state)
        feedback = state.review.summary
        if state.review.issues:
            feedback = (feedback or "") + "\n" + "\n".join(state.review.issues)
        return feedback

    async def _run_validation_gate(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
    ) -> str:
        if state.last_transition == Transition.VALIDATION_STARTED:
            self._invalidate_validation_cache(state)

        await self._ensure_validation_results(item, state, runs_dir)

        if all(result.passed for result in state.validation_results):
            record_transition(runs_dir, state, Transition.VALIDATION_PASSED)
            return "pass"

        record_transition(runs_dir, state, Transition.VALIDATION_FAILED)
        save_state(runs_dir, state)
        return "fail"

    async def _work_validate_review_attempt(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
        feedback: str | None,
        *,
        preserve_session: bool = False,
    ) -> str:
        settings = self.workspace.manifest.settings
        current_feedback = feedback

        while True:
            gate = await self._run_validation_gate(item, state, runs_dir)
            if gate == "pass":
                break

            if state.validation_repair_count >= settings.max_validation_repairs_per_attempt:
                record_transition(runs_dir, state, Transition.VALIDATION_FAILED)
                return "fail"

            state.validation_repair_count += 1
            self._invalidate_validation_cache(state)
            repair_feedback = self._validation_failure_feedback(state)
            work_ok = await self._run_work_phase(
                item,
                state,
                runs_dir,
                current_feedback,
                preserve_session=False,
                validation_failure_feedback=repair_feedback,
            )
            if not work_ok:
                return "fail"

            await self._reload_workspace()
            self._maybe_apply_restructure(item, runs_dir)
            item = self.workspace.get(item.id) or item
            if item.status == ItemStatus.SUPERSEDED:
                return "superseded"
            current_feedback = feedback

        return await self._run_review_phase(
            item,
            state,
            runs_dir,
            current_feedback,
            preserve_session=preserve_session,
        )

    async def _ensure_validation_results(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
    ) -> None:
        if state.validation_attempt == state.logical_attempt:
            return

        self.renderer.rule(
            f"VALIDATE {item.id} attempt={state.logical_attempt} "
            f"repair={state.validation_repair_count}"
        )
        record_transition(runs_dir, state, Transition.VALIDATION_STARTED)
        commands = self._resolved_validation_commands(item)
        results = await run_validation_commands(
            self.config.workspace_root,
            commands,
            timeout_seconds=(
                self.workspace.manifest.settings.validation_timeout_seconds
            ),
        )
        state.validation_attempt = state.logical_attempt
        state.validation_results = results
        state.changed_paths = self._item_paths(state)
        save_state(runs_dir, state)

        attempt_dir = attempts_dir(runs_dir, state.logical_attempt)
        payload = {
            "logical_attempt": state.logical_attempt,
            "validation_repair_count": state.validation_repair_count,
            "results": [
                result.model_dump(mode="json")
                for result in results
            ],
        }
        write_json(attempt_dir / "validation-results.json", payload)
        if state.validation_repair_count:
            write_json(
                attempt_dir
                / f"validation-results-repair-{state.validation_repair_count}.json",
                payload,
            )

    def _ensure_no_active_execution_for_run(self, todo_id: str | None) -> None:
        active = self._find_active_execution()
        if active is None:
            return
        item, state = active
        if todo_id is not None and item.id != todo_id:
            raise TodosToolError(
                f"Item {item.id} is already in progress "
                f"(phase={state.phase.value}). Use `todos-tool resume` instead."
            )
        raise TodosToolError(
            f"Item {item.id} is already in progress "
            f"(phase={state.phase.value}). Use `todos-tool resume` instead."
        )

    def _find_active_execution(self) -> tuple[TodoItem, RunState] | None:
        if self.workspace is None:
            return None
        for item in self.workspace.items:
            if item.status == ItemStatus.IN_PROGRESS:
                state = load_state(self.workspace.runs_dir(item.id))
                if state is not None:
                    return item, state
                return item, new_run_state(item.id, None)
            state = load_state(self.workspace.runs_dir(item.id))
            if state and state.phase != Phase.IDLE:
                return item, state
        return None

    async def _run_work_phase(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
        feedback: str | None,
        *,
        preserve_session: bool = False,
        validation_failure_feedback: str | None = None,
    ) -> bool:
        settings = self.workspace.manifest.settings
        continuation: str | None = None
        if not preserve_session:
            state.session_restart_count = 0

        while True:
            state.phase = Phase.WORK
            state.session_number += 1
            transition = (
                Transition.WORK_SESSION_RESTARTED
                if state.session_restart_count > 0
                else Transition.WORK_SESSION_STARTED
            )
            record_transition(runs_dir, state, transition)

            attempt_dir = attempts_dir(runs_dir, state.logical_attempt)
            attempt_dir.mkdir(parents=True, exist_ok=True)
            events_path = attempt_dir / f"work-session-{state.session_number}.ndjson"
            log_path = attempt_dir / f"work-session-{state.session_number}.log"
            prompt_path = attempt_dir / f"work-prompt-{state.session_number}.md"
            prompt_kwargs = self._prompt_kwargs(item)
            prompt = build_work_prompt(
                item,
                logical_attempt=state.logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                todos_dir=self.config.todos_dir,
                previous_feedback=feedback,
                validation_failure_feedback=validation_failure_feedback,
                continuation=continuation,
                **prompt_kwargs,
            )
            prompt_path.write_text(prompt, encoding="utf-8")

            self.renderer.rule(
                f"WORK {item.id} attempt={state.logical_attempt} "
                f"session={state.session_number}"
            )

            session_renderer = ConsoleRenderer.with_file_logging(
                self.renderer,
                log_path,
            )

            try:
                result = await self.client.run_session(
                    workspace=self.config.workspace_root,
                    prompt=prompt,
                    prompt_path=prompt_path,
                    phase="work",
                    timeout_seconds=settings.work_timeout_seconds,
                    events_path=events_path,
                    log_path=log_path,
                    renderer=session_renderer,
                    on_agent_started=lambda pid: _persist_agent_pid(
                        runs_dir, state, pid
                    ),
                )
            except UserInterrupted as exc:
                state.agent_pid = None
                state.last_error = str(exc)
                save_state(runs_dir, state)
                raise
            except CursorEnvironmentError:
                raise
            except CursorSessionError as exc:
                state.last_error = str(exc)
                state.agent_pid = None
                save_state(runs_dir, state)
                if not exc.recoverable:
                    raise
                if state.session_restart_count >= settings.max_session_restarts_per_phase:
                    state.review.summary = f"Work phase failed: {exc}"
                    record_transition(runs_dir, state, Transition.WORK_PHASE_FAILED)
                    return False
                state.session_restart_count += 1
                continuation = build_continuation_context(
                    item=item,
                    logical_attempt=state.logical_attempt,
                    phase="work",
                    workspace_root=self.config.workspace_root,
                    previous_summary=state.work_summary,
                    failure_reason=str(exc),
                    item_paths=self._item_paths(state),
                    todos_dir=self.config.todos_dir,
                )
                continue

            state.work_summary = _extract_summary(result)
            state.changed_paths = self._item_paths(state)
            state.session_restart_count = 0
            state.agent_pid = None
            record_transition(runs_dir, state, Transition.WORK_PHASE_READY)
            return True

    async def _run_review_phase(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
        feedback: str | None,
        *,
        preserve_session: bool = False,
    ) -> str:
        settings = self.workspace.manifest.settings
        continuation: str | None = None
        if (
            not state.validation_results
            or state.validation_attempt != state.logical_attempt
        ):
            gate = await self._run_validation_gate(item, state, runs_dir)
            if gate != "pass":
                return "fail"
        if not preserve_session:
            state.session_restart_count = 0
            state.session_number = 0

        while True:
            state.phase = Phase.REVIEW
            state.session_number += 1
            transition = (
                Transition.REVIEW_SESSION_RESTARTED
                if state.session_restart_count > 0
                else Transition.REVIEW_SESSION_STARTED
            )
            record_transition(runs_dir, state, transition)

            attempt_dir = attempts_dir(runs_dir, state.logical_attempt)
            attempt_dir.mkdir(parents=True, exist_ok=True)
            events_path = attempt_dir / f"review-session-{state.session_number}.ndjson"
            log_path = attempt_dir / f"review-session-{state.session_number}.log"

            item_paths = self._item_paths(state)
            review_ctx = build_review_context(
                self.config.workspace_root,
                baseline_head=state.baseline_head,
                paths=item_paths or None,
            )
            prompt_path = attempt_dir / f"review-prompt-{state.session_number}.md"
            prompt_kwargs = self._prompt_kwargs(item)
            prompt = build_review_prompt(
                item,
                logical_attempt=state.logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                work_summary=state.work_summary,
                git_diff=review_ctx.format_summary(),
                git_status=review_ctx.status_porcelain,
                authoritative_validation=state.validation_results,
                continuation=continuation,
                **prompt_kwargs,
            )

            prompt_path.write_text(prompt, encoding="utf-8")
            self.renderer.rule(
                f"REVIEW {item.id} attempt={state.logical_attempt} "
                f"session={state.session_number}"
            )

            session_renderer = ConsoleRenderer.with_file_logging(
                self.renderer,
                log_path,
            )

            try:
                result = await self.client.run_session(
                    workspace=self.config.workspace_root,
                    prompt=prompt,
                    prompt_path=prompt_path,
                    phase="review",
                    timeout_seconds=settings.review_timeout_seconds,
                    events_path=events_path,
                    log_path=log_path,
                    renderer=session_renderer,
                    on_agent_started=lambda pid: _persist_agent_pid(
                        runs_dir, state, pid
                    ),
                )
            except UserInterrupted as exc:
                state.agent_pid = None
                state.last_error = str(exc)
                save_state(runs_dir, state)
                raise
            except CursorEnvironmentError:
                raise
            except CursorSessionError as exc:
                state.last_error = str(exc)
                state.agent_pid = None
                save_state(runs_dir, state)
                if state.session_restart_count >= settings.max_session_restarts_per_phase:
                    state.review.summary = f"Review session failed: {exc}"
                    state.review.issues = [str(exc)]
                    record_transition(runs_dir, state, Transition.REVIEW_FAILED)
                    return "fail"
                state.session_restart_count += 1
                continuation = build_continuation_context(
                    item=item,
                    logical_attempt=state.logical_attempt,
                    phase="review",
                    workspace_root=self.config.workspace_root,
                    previous_summary=state.work_summary,
                    failure_reason=str(exc),
                    item_paths=item_paths,
                    todos_dir=self.config.todos_dir,
                    validation_notes=format_validation_results(
                        state.validation_results
                    ),
                )
                continue

            state.agent_pid = None

            try:
                decision = parse_review_decision(result.assistant_text)
                accept_decision(
                    decision,
                    item,
                    state.logical_attempt,
                    state.validation_results,
                )
            except ReviewError as exc:
                state.review.summary = str(exc)
                state.review.issues = [str(exc)]
                write_json(
                    attempt_dir / f"review-decision-{state.session_number}.json",
                    {"error": str(exc), "raw": result.assistant_text[-4000:]},
                )
                record_transition(runs_dir, state, Transition.REVIEW_FAILED)
                return "fail"

            write_json(
                attempt_dir / f"review-decision-{state.session_number}.json",
                decision.model_dump(mode="json"),
            )
            state.review.decision = decision.decision
            state.review.summary = decision.summary
            state.review.issues = decision.issue_strings()

            if decision.decision == "pass":
                record_transition(runs_dir, state, Transition.REVIEW_PASSED)
                return "pass"
            if decision.decision == "blocked":
                state.blocked_reason = decision.summary
                record_transition(runs_dir, state, Transition.ITEM_BLOCKED)
                return "blocked"

            record_transition(runs_dir, state, Transition.REVIEW_FAILED)
            return "fail"

    async def _commit_item(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
    ) -> None:
        if not self._resolve_auto_commit():
            self.renderer.info(
                f"{item.id}: auto_commit disabled; marked done without git commit"
            )
            self._finalize_item_done(item, None, state.work_summary or "")
            state.phase = Phase.IDLE
            record_transition(runs_dir, state, Transition.ITEM_DONE)
            return

        if state.commit_state == CommitState.COMPLETED and state.commit_sha:
            verify_commit_sha(self.config.workspace_root, state.commit_sha)
            self._finalize_item_done(item, state.commit_sha, state.work_summary or "")
            return

        state.phase = Phase.COMMIT
        state.commit_state = CommitState.STARTED
        record_transition(runs_dir, state, Transition.COMMIT_STARTED)

        summary = state.work_summary or state.review.summary or ""
        item = self.workspace.get(item.id) or item
        item.status = ItemStatus.DONE
        item.result.completed_at = datetime.now(timezone.utc)
        item.result.summary = summary
        item.result.commit_sha = None
        self._persist_item(item)

        skip_commit = self.config.skip_commit or not self._resolve_auto_commit()
        try:
            result = finalize_worktree(
                self.config.workspace_root,
                commit_prefix=self.project_context.git.commit_prefix,
                skip_commit=skip_commit,
                baseline_head=state.baseline_head,
            )
        except GitError:
            item = self.workspace.get(item.id) or item
            item.status = ItemStatus.IN_PROGRESS
            item.result.completed_at = None
            item.result.summary = None
            self._persist_item(item)
            state.commit_state = CommitState.FAILED
            record_transition(runs_dir, state, Transition.COMMIT_FAILED)
            raise

        sha = result.commit_sha
        item = self.workspace.get(item.id) or item
        item.result.commit_sha = sha
        self._persist_item(item)

        state.commit_state = CommitState.COMPLETED
        state.commit_sha = sha
        state.provenance_kind = result.provenance_kind
        record_transition(
            runs_dir,
            state,
            Transition.COMMIT_COMPLETED,
            sha=sha,
        )
        state.phase = Phase.IDLE
        record_transition(runs_dir, state, Transition.ITEM_DONE, sha=sha)
        self.renderer.info(result.message)

    def _finalize_item_done(
        self,
        item: TodoItem,
        commit_sha: str | None,
        summary: str,
    ) -> None:
        item = self.workspace.get(item.id) or item
        item.status = ItemStatus.DONE
        item.result.completed_at = datetime.now(timezone.utc)
        item.result.commit_sha = commit_sha
        item.result.summary = summary
        self._persist_item(item)

    def _persist_item(self, item: TodoItem) -> None:
        save_item(self.workspace, item)
        self.workspace._by_id[item.id] = item

    def _maybe_apply_restructure(self, item: TodoItem, runs_dir: Path) -> None:
        proposal_path = runs_dir / "restructure-proposal.json"
        try:
            proposal = load_restructure_proposal(proposal_path)
        except RestructuringError as exc:
            self.renderer.warn(str(exc))
            return
        if proposal is None:
            return
        try:
            self.workspace = apply_restructure_proposal(
                self.workspace,
                item,
                proposal,
                proposal_path=proposal_path,
            )
            self.renderer.info(f"Applied restructuring proposal for {item.id}")
        except RestructuringError as exc:
            self.renderer.warn(f"Restructuring rejected: {exc}")


def _load_legacy_pre_dirty_fingerprints(runs_dir: Path) -> dict[str, str]:
    """Read pre_dirty_fingerprints from legacy state.json for resume safety."""
    path = state_path(runs_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = data.get("pre_dirty_fingerprints")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _classify_item_outcome(item: TodoItem | None) -> str:
    if item is None:
        return "failed"
    if item.status == ItemStatus.SUPERSEDED:
        return "skipped"
    if item.status == ItemStatus.BLOCKED:
        return "blocked"
    if item.status == ItemStatus.IN_PROGRESS:
        return "retryable"
    return "failed"


def _apply_outcome(report: RunReport, item_id: str, outcome: str) -> None:
    if outcome == "completed":
        report.completed.append(item_id)
    elif outcome == "skipped":
        report.skipped.append(item_id)
    elif outcome == "blocked":
        report.blocked.append(item_id)
    elif outcome == "retryable":
        report.retryable.append(item_id)
    else:
        report.failed.append(item_id)


def _extract_summary(result: SessionResult) -> str:
    text = result.assistant_text.strip()
    if len(text) <= 4000:
        return text
    head = 1500
    tail = 2400
    return (
        text[:head]
        + f"\n... truncated ({len(text)} chars total) ...\n"
        + text[-tail:]
    )


def _resolve_auto_commit(
    *,
    cli_auto_commit: bool | None,
    manifest_auto_commit: bool | None,
) -> bool:
    if cli_auto_commit is not None:
        return cli_auto_commit
    return manifest_auto_commit if manifest_auto_commit is not None else True


def _persist_agent_pid(runs_dir: Path, state: RunState, pid: int) -> None:
    state.agent_pid = pid
    save_state(runs_dir, state)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
