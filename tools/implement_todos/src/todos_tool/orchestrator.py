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
    ReviewError,
    RestructuringError,
    SchedulingError,
    TodosToolError,
    UserInterrupted,
)
from todos_tool.git_service import (
    commit,
    ensure_git_repo,
    has_staged_changes,
    head_sha,
    paths_changed_since,
    refuse_if_dirty,
    stage_paths,
    staged_diff_stat,
    status,
    diff_text,
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
from todos_tool.scheduler import next_ready


@dataclass
class RunConfig:
    workspace_root: Path
    todos_dir: str = "todos"
    allow_dirty: bool = False
    no_color: bool = False
    model: str | None = None
    stop_on_failure: bool | None = None
    agent_bin: str | None = None
    skip_probe: bool = False
    dry_run_prompts: bool = False


@dataclass
class RunReport:
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.renderer = ConsoleRenderer(no_color=config.no_color)
        self.workspace = load_workspace(config.workspace_root, config.todos_dir)
        self.client = CursorClient(
            agent_bin=config.agent_bin,
            model=_resolve_model(
                cli_model=config.model,
                manifest_model=self.workspace.manifest.settings.model,
            ),
            no_color=config.no_color,
            skip_probe=config.skip_probe,
            parse_error_threshold=self.workspace.manifest.settings.parse_error_threshold,
        )
        self._pre_existing_dirty: set[str] = set()

    async def run(self, todo_id: str | None = None) -> RunReport:
        ensure_git_repo(self.config.workspace_root)
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
            except SchedulingError:
                break

            try:
                await self._execute_item(item)
                report.completed.append(item.id)
            except (CursorEnvironmentError, UserInterrupted):
                raise
            except TodosToolError as exc:
                self.renderer.error(f"{item.id}: {exc}")
                refreshed = self.workspace.get(item.id)
                if refreshed and refreshed.status == ItemStatus.BLOCKED:
                    report.blocked.append(item.id)
                else:
                    report.failed.append(item.id)
                if stop_on_failure or todo_id is not None:
                    break
            finally:
                # Reload workspace after each item
                self.workspace = load_workspace(
                    self.config.workspace_root,
                    self.config.todos_dir,
                )

            if todo_id is not None:
                break

        return report

    async def resume(self) -> RunReport:
        """Resume any in_progress item from persisted state + git reality."""
        ensure_git_repo(self.config.workspace_root)
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

        in_progress = [
            i for i in self.workspace.items if i.status == ItemStatus.IN_PROGRESS
        ]
        if not in_progress:
            # Also look for run state without status update
            for item in self.workspace.items:
                state = load_state(self.workspace.runs_dir(item.id))
                if state and state.phase != Phase.IDLE and item.status == ItemStatus.PENDING:
                    in_progress.append(item)
                    break

        if not in_progress:
            self.renderer.info("Nothing to resume; starting normal run")
            return await self.run()

        item = in_progress[0]
        self.renderer.info(f"Resuming {item.id}")
        runs_dir = self.workspace.runs_dir(item.id)
        prior = load_state(runs_dir)
        if prior and prior.agent_pid:
            if _pid_alive(prior.agent_pid):
                self.renderer.warn(
                    f"Previous Cursor agent may still be running (pid={prior.agent_pid}). "
                    "Resume starts a new session; stop that pid manually if it conflicts."
                )
            else:
                prior.agent_pid = None
                save_state(runs_dir, prior)
        report = RunReport()
        try:
            await self._execute_item(item, resuming=True)
            report.completed.append(item.id)
        except (CursorEnvironmentError, UserInterrupted):
            raise
        except TodosToolError as exc:
            self.renderer.error(f"{item.id}: {exc}")
            report.failed.append(item.id)
        return report

    async def _execute_item(self, item: TodoItem, *, resuming: bool = False) -> None:
        settings = self.workspace.manifest.settings
        runs_dir = self.workspace.runs_dir(item.id)
        state = load_state(runs_dir)

        if state and state.commit_state == CommitState.COMPLETED and state.commit_sha:
            # Prevent duplicate commits after crash during status update
            self._finalize_item_done(item, state.commit_sha, state.work_summary or "")
            return

        if state is None:
            baseline = head_sha(self.config.workspace_root)
            state = new_run_state(item.id, baseline)
            save_state(runs_dir, state)

        if item.status == ItemStatus.PENDING:
            item.status = ItemStatus.IN_PROGRESS
            save_item(self.workspace, item)

        feedback: str | None = state.review.summary
        if state.review.issues:
            feedback = (feedback or "") + "\nIssues:\n" + "\n".join(
                f"- {i}" for i in state.review.issues
            )

        # Resume mid-commit
        if state.phase == Phase.COMMIT and state.commit_state == CommitState.STARTED:
            await self._commit_item(item, state, runs_dir)
            return

        # Resume mid-review: re-run review for current attempt
        if (
            resuming
            and state.phase == Phase.REVIEW
            and state.last_transition
            in (Transition.REVIEW_SESSION_STARTED, Transition.REVIEW_SESSION_RESTARTED)
        ):
            await self._run_review_phase(item, state, runs_dir, feedback)
            return

        start_attempt = state.logical_attempt or 1
        if state.logical_attempt == 0:
            start_attempt = 1

        # If previous attempt failed review, continue from next attempt
        if state.last_transition == Transition.REVIEW_FAILED:
            start_attempt = state.logical_attempt + 1
            feedback = state.review.summary
            if state.review.issues:
                feedback = (feedback or "") + "\n" + "\n".join(state.review.issues)

        for attempt in range(start_attempt, settings.max_attempts + 1):
            state.logical_attempt = attempt
            state.session_number = 0
            state.session_restart_count = 0
            state.phase = Phase.WORK
            state.commit_state = CommitState.NONE
            record_transition(runs_dir, state, Transition.ATTEMPT_STARTED)

            work_ok = await self._run_work_phase(item, state, runs_dir, feedback)
            if not work_ok:
                continue

            # Optional restructuring after work
            self._maybe_apply_restructure(item, runs_dir)
            item = self.workspace.get(item.id) or item
            if item.status == ItemStatus.SUPERSEDED:
                self.renderer.info(f"{item.id} superseded; stopping item")
                return

            review_outcome = await self._run_review_phase(
                item, state, runs_dir, feedback
            )
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
            feedback = state.review.summary
            if state.review.issues:
                feedback = (feedback or "") + "\n" + "\n".join(state.review.issues)

        item.status = ItemStatus.BLOCKED
        save_item(self.workspace, item)
        state.blocked_reason = f"Exceeded {settings.max_attempts} logical attempts"
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)
        raise TodosToolError(state.blocked_reason)

    async def _run_work_phase(
        self,
        item: TodoItem,
        state: RunState,
        runs_dir: Path,
        feedback: str | None,
    ) -> bool:
        settings = self.workspace.manifest.settings
        continuation: str | None = None

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
            prompt = build_work_prompt(
                item,
                logical_attempt=state.logical_attempt,
                previous_feedback=feedback,
                continuation=continuation,
            )
            (attempt_dir / f"work-prompt-{state.session_number}.md").write_text(
                prompt, encoding="utf-8"
            )

            self.renderer.rule(
                f"WORK {item.id} attempt={state.logical_attempt} "
                f"session={state.session_number}"
            )

            try:
                result = await self.client.run_session(
                    workspace=self.config.workspace_root,
                    prompt=prompt,
                    phase="work",
                    timeout_seconds=settings.work_timeout_seconds,
                    events_path=events_path,
                    log_path=log_path,
                    renderer=self.renderer,
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
                    record_transition(runs_dir, state, Transition.REVIEW_FAILED)
                    return False
                state.session_restart_count += 1
                continuation = build_continuation_context(
                    item=item,
                    logical_attempt=state.logical_attempt,
                    phase="work",
                    workspace_root=self.config.workspace_root,
                    previous_summary=state.work_summary,
                    failure_reason=str(exc),
                )
                continue

            state.work_summary = _extract_summary(result)
            state.changed_paths = paths_changed_since(
                self.config.workspace_root,
                state.baseline_head or "HEAD",
                self._pre_existing_dirty,
            )
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
    ) -> str:
        settings = self.workspace.manifest.settings
        continuation: str | None = None
        state.session_restart_count = 0
        state.session_number = 0

        while True:
            state.phase = Phase.REVIEW
            state.session_number += 1
            transition = (
                Transition.REVIEW_SESSION_RESTARTED
                if continuation
                else Transition.REVIEW_SESSION_STARTED
            )
            record_transition(runs_dir, state, transition)

            attempt_dir = attempts_dir(runs_dir, state.logical_attempt)
            attempt_dir.mkdir(parents=True, exist_ok=True)
            events_path = attempt_dir / f"review-session-{state.session_number}.ndjson"
            log_path = attempt_dir / f"review-session-{state.session_number}.log"

            st = status(self.config.workspace_root)
            git_diff = diff_text(self.config.workspace_root)
            prompt = build_review_prompt(
                item,
                logical_attempt=state.logical_attempt,
                work_summary=state.work_summary,
                git_diff=git_diff if not continuation else (continuation + "\n\n" + git_diff),
                git_status=st.porcelain,
            )
            if continuation:
                prompt += "\n\n## Continuation\n" + continuation

            (attempt_dir / f"review-prompt-{state.session_number}.md").write_text(
                prompt, encoding="utf-8"
            )
            self.renderer.rule(
                f"REVIEW {item.id} attempt={state.logical_attempt} "
                f"session={state.session_number}"
            )

            try:
                result = await self.client.run_session(
                    workspace=self.config.workspace_root,
                    prompt=prompt,
                    phase="review",
                    timeout_seconds=settings.review_timeout_seconds,
                    events_path=events_path,
                    log_path=log_path,
                    renderer=self.renderer,
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
                )
                continue

            state.agent_pid = None

            try:
                decision = parse_review_decision(result.assistant_text)
                accept_decision(decision, item, state.logical_attempt)
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
        settings = self.workspace.manifest.settings
        if not settings.auto_commit:
            self._finalize_item_done(item, None, state.work_summary or "")
            state.phase = Phase.IDLE
            record_transition(runs_dir, state, Transition.ITEM_DONE)
            return

        # Duplicate-commit prevention
        if state.commit_state == CommitState.COMPLETED and state.commit_sha:
            self._finalize_item_done(item, state.commit_sha, state.work_summary or "")
            return

        state.phase = Phase.COMMIT
        state.commit_state = CommitState.STARTED
        record_transition(runs_dir, state, Transition.COMMIT_STARTED)

        paths = paths_changed_since(
            self.config.workspace_root,
            state.baseline_head or "HEAD",
            self._pre_existing_dirty,
        )
        # Never stage todos run artifacts or pre-existing dirty paths
        paths = [
            p
            for p in paths
            if not p.startswith(f"{self.config.todos_dir}/runs/")
            and p not in self._pre_existing_dirty
        ]

        summary = state.work_summary or state.review.summary or ""
        # Prepare item metadata for inclusion in the same commit (sha filled after).
        item.status = ItemStatus.DONE
        item.result.completed_at = datetime.now(timezone.utc)
        item.result.summary = summary
        item.result.commit_sha = None
        save_item(self.workspace, item)
        if item.source_file:
            item_rel = f"{self.config.todos_dir}/{item.source_file}"
            if item_rel not in paths:
                paths.append(item_rel)

        if not paths:
            state.commit_state = CommitState.FAILED
            record_transition(runs_dir, state, Transition.COMMIT_FAILED)
            raise GitError("Review passed but no stageable paths found for commit")

        message = ""
        try:
            stage_paths(self.config.workspace_root, paths)
            if not has_staged_changes(self.config.workspace_root):
                raise GitError("Staging produced no staged changes")
            message = generate_commit_message(
                item, staged_diff_stat(self.config.workspace_root)
            )
            sha = commit(self.config.workspace_root, message)
        except GitError:
            # Roll status back so resume can retry commit
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
            self.workspace = apply_restructure_proposal(self.workspace, item, proposal)
            self.renderer.info(f"Applied restructuring proposal for {item.id}")
        except RestructuringError as exc:
            self.renderer.warn(f"Restructuring rejected: {exc}")


def _extract_summary(result: SessionResult) -> str:
    text = result.assistant_text.strip()
    if len(text) > 4000:
        return text[-4000:]
    return text


def _resolve_model(*, cli_model: str | None, manifest_model: str | None) -> str | None:
    """CLI ``--model`` overrides ``manifest.settings.model`` when set."""
    if cli_model is not None and cli_model.strip():
        return cli_model.strip()
    return manifest_model


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
