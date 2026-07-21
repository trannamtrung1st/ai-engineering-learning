"""Schedule, execute, review, commit, and resume TODO items."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from todos_tool.commit_message import generate_commit_message
from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.continuation import (
    apply_restructure_proposal,
    build_continuation_context,
    load_restructure_proposal,
    snapshot_pre_existing_dirty,
)
from todos_tool.cursor_client import CursorClient, SessionResult
from todos_tool.errors import (
    CursorEnvironmentError,
    CursorSessionError,
    GitError,
    PersistenceError,
    ReviewError,
    RestructuringError,
    SchedulingError,
    TodosToolError,
    UserInterrupted,
)
from todos_tool.git_service import (
    capture_pre_dirty_fingerprints,
    commit,
    ensure_git_repo,
    expand_path_prefixes,
    filter_stageable_paths,
    has_staged_changes,
    head_sha,
    paths_changed_since,
    paths_overlap,
    refuse_if_dirty,
    refuse_if_dirty_only_permitted,
    refuse_unrelated_staged,
    require_pre_dirty_fingerprints,
    require_usable_baseline,
    stage_paths,
    staged_diff_stat,
    status,
    diff_text,
    verify_commit_sha,
    verify_pre_dirty_unchanged,
)
from todos_tool.manifest import Workspace, load_workspace, save_item
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
    write_json,
)
from todos_tool.prompts import build_review_prompt, build_work_prompt
from todos_tool.reviewer import accept_decision, parse_review_decision
from todos_tool.scheduler import list_ready, next_ready
from todos_tool.validation_runner import (
    format_validation_results,
    resolve_validation_commands,
    run_validation_commands,
)


@dataclass
class RunConfig:
    workspace_root: Path
    todos_dir: str = "todos"
    allow_dirty: bool = False
    no_color: bool = False
    model: str | None = None
    stop_on_failure: bool | None = None
    auto_commit: bool | None = None
    agent_bin: str | None = None
    skip_probe: bool = False
    dry_run_prompts: bool = False


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
        self.workspace = load_workspace(config.workspace_root, config.todos_dir)
        self._client: CursorClient | None = None
        self._pre_existing_dirty: set[str] = set()

    @property
    def client(self) -> CursorClient:
        if self._client is None:
            self._client = CursorClient(
                agent_bin=self.config.agent_bin,
                model=_resolve_model(
                    cli_model=self.config.model,
                    manifest_model=self.workspace.manifest.settings.model,
                ),
                no_color=self.config.no_color,
                skip_probe=self.config.skip_probe,
                parse_error_threshold=self.workspace.manifest.settings.parse_error_threshold,
            )
        return self._client

    def _resolve_auto_commit(self) -> bool:
        return _resolve_auto_commit(
            cli_auto_commit=self.config.auto_commit,
            manifest_auto_commit=self.workspace.manifest.settings.auto_commit,
        )

    async def run(self, todo_id: str | None = None) -> RunReport:
        ensure_git_repo(self.config.workspace_root)
        self._ensure_no_active_execution_for_run(todo_id)
        st = refuse_if_dirty(
            self.config.workspace_root,
            allow_dirty=self.config.allow_dirty,
            todos_dir=self.config.todos_dir,
        )
        self._pre_existing_dirty = {
            p
            for p in snapshot_pre_existing_dirty(st)
            if not p.startswith(f"{self.config.todos_dir}/")
        }
        if self.config.dry_run_prompts:
            return self._write_dry_run_prompts(todo_id)

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
                # A retryable item remains in_progress, so continuing would
                # violate the single-active-item invariant.
                break

            self.workspace = load_workspace(
                self.config.workspace_root,
                self.config.todos_dir,
            )

            if todo_id is not None:
                break

        return report

    async def commit_item(self, item_id: str) -> str:
        """Commit trackable changes for a done item that has no commit SHA yet."""
        ensure_git_repo(self.config.workspace_root)
        self._pre_existing_dirty = set()

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

        commit_paths = self._collect_commit_paths(item, state)
        refuse_if_dirty_only_permitted(
            self.config.workspace_root,
            allow_dirty=self.config.allow_dirty,
            todos_dir=self.config.todos_dir,
            permitted_paths=set(commit_paths),
        )

        await self._commit_item(item, state, runs_dir)
        sha = state.commit_sha or item.result.commit_sha
        if not sha:
            raise GitError(f"{item_id}: commit finished without a SHA")
        return sha

    async def resume(self) -> RunReport:
        """Resume any in_progress item from persisted state + git reality."""
        ensure_git_repo(self.config.workspace_root)

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
                require_usable_baseline(
                    self.config.workspace_root,
                    state.baseline_head,
                    item_id=item.id,
                )
            permitted: set[str] = set()
            if state and state.baseline_head:
                permitted = {
                    path
                    for path in paths_changed_since(
                        self.config.workspace_root,
                        state.baseline_head,
                        set(),
                    )
                    if not path.startswith(f"{self.config.todos_dir}/runs/")
                }
                if item.source_file:
                    permitted.add(f"{self.config.todos_dir}/{item.source_file}")
            refuse_if_dirty_only_permitted(
                self.config.workspace_root,
                allow_dirty=self.config.allow_dirty,
                todos_dir=self.config.todos_dir,
                permitted_paths=permitted,
            )
            st = status(self.config.workspace_root)
            permitted_expanded = expand_path_prefixes(permitted)
            self._pre_existing_dirty = {
                path
                for path in snapshot_pre_existing_dirty(st)
                if not path.startswith(f"{self.config.todos_dir}/")
                and path not in permitted_expanded
                and not any(paths_overlap(path, allowed) for allowed in permitted)
            }
            if state is not None:
                fingerprints = require_pre_dirty_fingerprints(
                    state.pre_dirty_fingerprints,
                    self._pre_existing_dirty,
                    item_id=item.id,
                    resuming=True,
                )
                if not self.config.dry_run_prompts:
                    state.pre_dirty_fingerprints = fingerprints
                    save_state(runs_dir, state)
        else:
            st = refuse_if_dirty(
                self.config.workspace_root,
                allow_dirty=self.config.allow_dirty,
                todos_dir=self.config.todos_dir,
            )
            self._pre_existing_dirty = {
                path
                for path in snapshot_pre_existing_dirty(st)
                if not path.startswith(f"{self.config.todos_dir}/")
            }

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
            if in_progress and resume_state is not None:
                self._verify_pre_dirty_paths(in_progress[0], resume_state)
            return self._write_dry_run_prompts(target, resume_state)

        if not in_progress:
            self.renderer.info("Nothing to resume; starting normal run")
            return await self.run()

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
            # Prevent duplicate commits after crash during status update
            self._finalize_item_done(item, state.commit_sha, state.work_summary or "")
            return

        if state is None:
            baseline = head_sha(self.config.workspace_root)
            state = new_run_state(item.id, baseline)
            if self._pre_existing_dirty:
                state.pre_dirty_fingerprints = capture_pre_dirty_fingerprints(
                    self.config.workspace_root,
                    self._pre_existing_dirty,
                )
            save_state(runs_dir, state)
        elif resuming:
            require_usable_baseline(
                self.config.workspace_root,
                state.baseline_head,
                item_id=item.id,
            )
            state.pre_dirty_fingerprints = require_pre_dirty_fingerprints(
                state.pre_dirty_fingerprints,
                self._pre_existing_dirty,
                item_id=item.id,
                resuming=True,
            )
            save_state(runs_dir, state)

        if item.status == ItemStatus.PENDING:
            item.status = ItemStatus.IN_PROGRESS
            save_item(self.workspace, item)

        feedback: str | None = state.review.summary
        if state.review.issues:
            feedback = (feedback or "") + "\nIssues:\n" + "\n".join(
                f"- {i}" for i in state.review.issues
            )

        # Resume mid-commit (including failed attempts)
        if state.phase == Phase.COMMIT and state.commit_state in (
            CommitState.STARTED,
            CommitState.FAILED,
        ):
            self._verify_pre_dirty_paths(item, state)
            await self._commit_item(item, state, runs_dir)
            return

        # Resume after work completed or validation completed, before review
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

        # Resume mid-work: continue the same phase without resetting session numbers
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

        # If previous attempt failed review or validation, continue from next attempt
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
                item.status = ItemStatus.BLOCKED
                save_item(self.workspace, item)
                state.phase = Phase.IDLE
                record_transition(
                    runs_dir,
                    state,
                    Transition.ITEM_BLOCKED,
                    reason=state.blocked_reason,
                )
                raise TodosToolError(state.blocked_reason or "Item blocked by review")

            # fail → next logical attempt
            feedback = self._attempt_failure_feedback(state)

        item.status = ItemStatus.BLOCKED
        save_item(self.workspace, item)
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
            item.status = ItemStatus.BLOCKED
            save_item(self.workspace, item)
            state.phase = Phase.IDLE
            record_transition(
                runs_dir,
                state,
                Transition.ITEM_BLOCKED,
                reason=state.blocked_reason,
            )
            raise TodosToolError(state.blocked_reason or "Item blocked by review")
        raise TodosToolError(state.review.summary or "Review failed during resume")

    def _verify_pre_dirty_paths(self, item: TodoItem, state: RunState) -> None:
        verify_pre_dirty_unchanged(
            self.config.workspace_root,
            state.pre_dirty_fingerprints,
            item_id=item.id,
        )

    def _item_paths(self, state: RunState) -> list[str]:
        paths = paths_changed_since(
            self.config.workspace_root,
            state.baseline_head or "HEAD",
            self._pre_existing_dirty,
        )
        return [
            path
            for path in paths
            if not path.startswith(f"{self.config.todos_dir}/runs/")
        ]

    def _write_dry_run_prompts(
        self,
        todo_id: str | None,
        state: RunState | None = None,
    ) -> RunReport:
        """Write prompt previews without agents, validation, state, or item changes."""
        items = (
            [next_ready(self.workspace, todo_id)]
            if todo_id is not None
            else list_ready(self.workspace)
        )
        report = RunReport()
        st = status(self.config.workspace_root)
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
            work_prompt = build_work_prompt(
                item,
                logical_attempt=logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                todos_dir=self.config.todos_dir,
                previous_feedback=feedback,
                allow_full_check=self._allow_full_check(item),
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
                    diff_text(self.config.workspace_root, paths=item_paths)
                    if item_state
                    else "(not available before work executes)"
                ),
                git_status=st.porcelain,
                authoritative_validation=validation,
                prompt_only=validation is None,
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
        return resolve_validation_commands(self.workspace.manifest, item)

    def _allow_full_check(self, item: TodoItem) -> bool:
        return item.id.upper().startswith("SETUP-")

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
        self._verify_pre_dirty_paths(item, state)
        commands = self._resolved_validation_commands(item)
        results = await run_validation_commands(
            self.config.workspace_root,
            commands,
            timeout_seconds=(
                self.workspace.manifest.settings.validation_timeout_seconds
            ),
        )
        self._verify_pre_dirty_paths(item, state)
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
            prompt = build_work_prompt(
                item,
                logical_attempt=state.logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                todos_dir=self.config.todos_dir,
                previous_feedback=feedback,
                validation_failure_feedback=validation_failure_feedback,
                allow_full_check=self._allow_full_check(item),
                continuation=continuation,
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
                state.agent_pid = exc.agent_pid or state.agent_pid
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
            self._verify_pre_dirty_paths(item, state)
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
            self._verify_pre_dirty_paths(item, state)
            st = status(self.config.workspace_root)
            git_diff = diff_text(
                self.config.workspace_root,
                paths=item_paths,
            )
            prompt_path = attempt_dir / f"review-prompt-{state.session_number}.md"
            prompt = build_review_prompt(
                item,
                logical_attempt=state.logical_attempt,
                resolved_commands=self._resolved_validation_commands(item),
                work_summary=state.work_summary,
                git_diff=git_diff,
                git_status=st.porcelain,
                authoritative_validation=state.validation_results,
                continuation=continuation,
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
                state.agent_pid = exc.agent_pid or state.agent_pid
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
                # Malformed/contradictory review consumes a logical attempt
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

        # Duplicate-commit prevention
        if state.commit_state == CommitState.COMPLETED and state.commit_sha:
            verify_commit_sha(self.config.workspace_root, state.commit_sha)
            self._finalize_item_done(item, state.commit_sha, state.work_summary or "")
            return

        self._verify_pre_dirty_paths(item, state)

        state.phase = Phase.COMMIT
        state.commit_state = CommitState.STARTED
        record_transition(runs_dir, state, Transition.COMMIT_STARTED)

        paths = self._collect_commit_paths(item, state)
        summary = state.work_summary or state.review.summary or ""
        # Prepare item metadata for inclusion in the same commit (sha filled after).
        item.status = ItemStatus.DONE
        item.result.completed_at = datetime.now(timezone.utc)
        item.result.summary = summary
        item.result.commit_sha = None
        save_item(self.workspace, item)

        if not paths:
            item.status = ItemStatus.IN_PROGRESS
            item.result.completed_at = None
            item.result.summary = None
            save_item(self.workspace, item)
            state.commit_state = CommitState.FAILED
            record_transition(runs_dir, state, Transition.COMMIT_FAILED)
            raise GitError(
                "Review passed but no stageable paths found for commit "
                "(changes may be gitignored or already committed)"
            )

        message = ""
        try:
            refuse_unrelated_staged(
                self.config.workspace_root,
                todos_dir=self.config.todos_dir,
                approved_paths=set(paths),
            )
            stage_paths(
                self.config.workspace_root,
                paths,
                todos_dir=self.config.todos_dir,
            )
            if not has_staged_changes(self.config.workspace_root):
                raise GitError(
                    "Staging produced no staged changes "
                    "(paths may be gitignored or already committed)"
                )
            message = generate_commit_message(
                item, staged_diff_stat(self.config.workspace_root)
            )
            sha = commit(self.config.workspace_root, message)
        except GitError:
            # Roll status back so resume/commit can retry
            item.status = ItemStatus.IN_PROGRESS
            item.result.completed_at = None
            item.result.summary = None
            save_item(self.workspace, item)
            state.commit_state = CommitState.FAILED
            record_transition(runs_dir, state, Transition.COMMIT_FAILED)
            raise

        item.result.commit_sha = sha
        save_item(self.workspace, item)

        state.commit_state = CommitState.COMPLETED
        state.commit_sha = sha
        record_transition(runs_dir, state, Transition.COMMIT_COMPLETED, sha=sha)
        state.phase = Phase.IDLE
        record_transition(runs_dir, state, Transition.ITEM_DONE, sha=sha)
        self.renderer.info(f"Committed {item.id} as {sha[:8]} — {message}")

    def _finalize_item_done(
        self,
        item: TodoItem,
        commit_sha: str | None,
        summary: str,
    ) -> None:
        item.status = ItemStatus.DONE
        item.result.completed_at = datetime.now(timezone.utc)
        item.result.commit_sha = commit_sha
        item.result.summary = summary
        save_item(self.workspace, item)

    def _collect_commit_paths(self, item: TodoItem, state: RunState) -> list[str]:
        if state.changed_paths:
            paths = [
                path
                for path in state.changed_paths
                if not path.startswith(f"{self.config.todos_dir}/runs/")
                and path not in self._pre_existing_dirty
            ]
        else:
            paths = paths_changed_since(
                self.config.workspace_root,
                state.baseline_head or "HEAD",
                self._pre_existing_dirty,
            )
            paths = [
                path
                for path in paths
                if not path.startswith(f"{self.config.todos_dir}/runs/")
                and path not in self._pre_existing_dirty
            ]
        if item.source_file:
            item_rel = f"{self.config.todos_dir}/{item.source_file}"
            dirty_paths = set(status(self.config.workspace_root).changed_paths)
            if item_rel not in paths and item_rel in dirty_paths:
                paths.append(item_rel)
        return filter_stageable_paths(self.config.workspace_root, paths)

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


def _resolve_model(*, cli_model: str | None, manifest_model: str | None) -> str | None:
    """CLI ``--model`` overrides ``manifest.settings.model`` when set."""
    if cli_model is not None and cli_model.strip():
        return cli_model.strip()
    return manifest_model


def _resolve_auto_commit(
    *,
    cli_auto_commit: bool | None,
    manifest_auto_commit: bool | None,
) -> bool:
    """CLI ``--auto-commit true|false`` overrides manifest when set."""
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
