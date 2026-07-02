# We Check — Full Harness Improvement Plan (Phases 1–3 + UI/UX Screen Checklist)

Feed this entire file to an implementation agent.

**Repo:** `/Users/trungtran/MyPlace/Personal/Learning/ai-engineering-learning/projects/ai-harnessed_we-check-app`

**Scope:** Harness scripts, config, agent prompts, and harness docs only — do **not** change `apps/`, `packages/`, or application `tests/` unless a one-line Playwright `globalSetup` hook is strictly required and cannot be done harness-side.

**Do not git commit** unless explicitly asked.

---

## Problem statement

The Ralph loop (`npm run aih:loop`) is slow and retry-heavy because:

1. `aih:check` runs the **full** playwright-ui suite (~126 tests, ~5 min) per iteration even though `implementer.prompt.md` claims slice-scoped checks.
2. Implementer agents bundle cross-slice edits (e.g. `web-admin-users` + `export-service` + `web-instructor-session-monitor.spec.ts`); functional gates pass, then AI review fails late after ~10+ min wasted.
3. Doc drift (`reset_requirement_tag_on_doc_drift` in `common.sh`) sets `passes: false` on every slice referencing a changed tag, even when test case JSON is unchanged — 9+ slices regressed.
4. `testCaseGate.mode` is `"optional"` so Ralph runs with stale test artifacts.
5. Every iteration runs full integration + e2e even for small UI fixes.
6. Preview DB/auth fixtures race integration truncates → browser flakes.
7. UI/UX craft checks exist in `ui-visual-verification.md` but are not enforced as a **structured per-screen checklist** in agent prompts with mandatory screenshot evidence per screen/state.

**Goals after changes:**

| Metric | Today (approx.) | Target |
|--------|-----------------|--------|
| `aih:check` per iteration | ~10–12 min | ~3–5 min (slice path) |
| Iterations to pass a reopened slice | 5–10 | ≤3 when scope is correct |
| Review failures after green gates | Common (scope creep) | Rare (mechanical pre-check) |
| Doc edits mass-reopen slices | Yes | Only when test case artifacts change |
| UI screens verified with screenshots | Ad hoc | Every screen/state in slice, checklist logged |

---

# PHASE 1 — Quick wins

## 1.1 Slice-scoped Playwright in `aih:check`

**Files:** `ai-harness/scripts/run-checks.sh`, `ai-harness/scripts/lib/common.sh`, `ai-harness/workflows/ralph-loop.json`, `ai-harness/README.md`

Add to `ralph-loop.json` under `computationalChecks`:

```json
"playwrightScope": "slice",
"playwrightFullEveryN": 0
```

Values: `"slice"` | `"full"`. `playwrightFullEveryN`: `0` = never auto-full; if `> 0`, run full suite every N slice passes (track in `ai-harness/generated/playwright-full-counter.json` if needed).

When `SLICE_ID` is set AND `playwrightScope` is `"slice"`:

- Resolve spec from, in order: slice `testRequirements.playwright[0]`, `playwright_output_path_for_slice()`, `playwright-regression-index.json` for slice id.
- Run from `tests/playwright-ui` workspace: `npx playwright test <relative-spec>` — **not** `npm run test:playwright-ui`.
- If no spec exists for slice, skip with clear log (optional script stays optional).

When `playwrightScope` is `"full"` or `SLICE_ID` empty: keep current full-suite behavior.

Record in `*-checks.json`: `playwrightScope` used, spec path, test count if available.

Align `implementer.prompt.md` wording with actual behavior.

---

## 1.2 Mechanical scope gate

**Files:** NEW `ai-harness/scripts/check-slice-scope.sh`, `ai-harness/scripts/ralph-once.sh`, `ai-harness/workflows/ralph-loop.json`, `ai-harness/scripts/lib/common.sh`

**New script:** `check-slice-scope.sh <sliceId>`

Build allowlist from slice JSON:

- `completionArtifacts[]`
- `testRequirements.unit/integration/component/playwright` paths
- `ai-harness/generated/runs/screenshots/<sliceId>/`
- `ai-harness/state/progress.md`, `ai-harness/state/guardrails.md` (append-only)
- `ai-harness/whole-app-backlog.json` (only when updating this slice's `testRequirements`)

Read `scopeAllowlist` from `ralph-loop.json` `computationalChecks.scopeAllowlist` — shared frontend infra paths allowed only for `agent: "frontend"`:

- `apps/web/src/lib/auth-session.ts`
- `apps/web/src/components/auth/setup-guard.tsx`
- `apps/web/src/app/providers.tsx`
- `apps/web/src/lib/auth-boot-context.tsx` (if present)

Read slice `excludes` from backlog (Phase 2.4) — any changed file under another slice's `completionArtifacts` prefix is a violation.

Compare `git diff --name-only HEAD` (staged + unstaged) to allowlist (prefix or exact match).

Exit `0` if in scope; exit `1` printing violating paths one per line.

**Wire in `ralph-once.sh`:** AFTER `run-checks.sh` passes, BEFORE `run-browser-test.sh`:

- Run `check-slice-scope.sh "$SLICE_ID"`
- On failure: `append_guardrail` with file list, `append_progress "$SLICE_ID" "scope_failed"`, exit `1`

---

## 1.3 Implementer scope rules

**File:** `ai-harness/agents/implementer.prompt.md`

Add under **Rules**:

- Edit **only** paths under this slice's `completionArtifacts` and `testRequirements`, harness state append-only files, and `scopeAllowlist` paths when `guardrails.md` names them for the current failure.
- Do **not** modify another slice's `tests/playwright-ui/scenarios/web-*.spec.ts` except this slice's own spec.
- Do **not** fix other slices' application code or tests — signal `SLICE_BLOCKED <reason>` if a prior gate requires out-of-slice work.
- Do **not** bundle instructor export, monitor, or unrelated admin routes unless this slice's `completionArtifacts` include them.

---

## 1.4 TestGen gate required

**Files:** `ai-harness/workflows/ralph-loop.json`, `ai-harness/README.md`

- Set `"testCaseGate": { "mode": "required" }`
- Document workflow after doc edits:

```bash
npm run aih:testgen:drift && npm run aih:testgen:loop && npm run aih:loop
```

- Optional: `npm run aih:loop:safe` — wrapper that exits `1` if any referenced tag has `current: false` in `test-case-index.json`

---

# PHASE 2 — Structural

## 2.1 Smarter doc-drift reopen policy

**Files:** `ai-harness/scripts/lib/common.sh`, `ai-harness/scripts/check-test-case-drift.sh`, `ai-harness/README.md`

**Current:** doc fingerprint change → `passes: false` on ALL slices referencing tag.

**New:**

- On doc fingerprint change: set `test-case-index` `current: false` for tag, append guardrail — **do not** reset `passes` on slices yet.
- Add `mark_slices_stale_for_tag(tag)` called only when TestGen successfully regenerates artifact: then set `passes: false` **only** for slices whose `acceptance[]` includes that tag AND `reverifyOnDrift` is not `false`.
- Optional backlog field per slice: `"reverifyOnDrift": false` (default true when absent).
- Document two-phase model in README: drift → testgen → slices reopen.

---

## 2.2 Tiered check profiles

**Files:** `ralph-loop.json`, `run-checks.sh`, `run-logged-check.sh`, `package.json`

Add to `ralph-loop.json`:

```json
"computationalChecks": {
  "profiles": {
    "fast": ["typecheck", "lint", "test:unit", "test:playwright-ui"],
    "full": ["typecheck", "lint", "build", "test:unit", "test:integration", "test:e2e", "test:playwright-ui"]
  },
  "gateProfile": "full"
}
```

- `run-checks.sh`: accept `--profile fast|full` or env `AIH_CHECK_PROFILE` (default `full` for ralph-once gate).
- `fast` profile: skip build/integration/e2e; slice-scoped playwright per 1.1.
- Implementer self-check: `npm run aih:check -- <sliceId> --profile fast`; harness gate always uses `full`.

---

## 2.3 Reviewer policy + bounded diff

**Files:** `ai-harness/agents/reviewer.prompt.md`, `run-ai-review.sh`, `build-prompt.sh`, `ai-harness/docs/ux-bug-logging.md`

- Inject mechanical scope gate result: `scope_gate: pass`, `allowlisted_files: [...]`
- If scope gate passed, checklist item 1 trusts allowlist — focus acceptance/craft only.
- P3 UX bugs from browser test: reviewer notes as non-blocking; do **not** `REVIEW_FAIL` for P3 alone unless slice `completionArtifacts` explicitly include nav/breadcrumb work.
- Bundle git diff filtered to allowlisted paths only.

---

## 2.4 Backlog slice dependencies

**Files:** `ai-harness/whole-app-backlog.json`, `build-prompt.sh`, `check-slice-scope.sh`

Add optional fields: `"excludes": [...]`, `"notes": "..."`

Populate `excludes` for creep-prone slices:

- `web-admin-users` → excludes `web-instructor-reports`, `web-admin-reports-export`, `web-instructor-session-monitor`
- `web-admin-users-import` → note: import-only; exclude list CRUD paths owned by `web-admin-users`

`build-prompt.sh`: inject `{{SLICE_EXCLUDES}}` and `{{SLICE_NOTES}}` into implementer prompt.

`check-slice-scope.sh` enforces `excludes`.

---

# PHASE 3 — Hardening & observability

## 3.1 Preview fixture isolation

**Files:** `ai-harness/docs/preview-runtime.md`, README; minimal Playwright `globalSetup` fix only if missing

- Document: Playwright `globalSetup` must `POST /auth/preview/refresh-fixtures` and wait for API health before UI login.
- Ensure refresh + login retry is idempotent (minimal change only if broken).
- Note: integration tests that truncate auth should not race browser gates without preview refresh.

---

## 3.2 Loop health dashboard

**Files:** NEW `ai-harness/scripts/loop-status.sh`, `package.json` → `"aih:status"`

Print:

- Pending slice count, next slice id
- Per-slice iteration counts since last `passed` (from `progress.md`)
- Tags with `test-case-index` `current: false`
- Latest `aih:check` duration from recent `*-check-*.log` if parseable
- Recent `scope_failed` / `review_failed` / `browser_test_failed` counts

Human-readable stdout; README one-liner only.

---

## 3.3 Regression budget

**Files:** `ralph-loop.json`, `ai-harness/docs/playwright-regression.md`, `tester.prompt.md`

- Add `browserTest.playwrightMaxCasesPerSlice` (e.g. `30`) — browser agent prioritizes P0/P1 when checklist exceeds budget.
- Full regression (`playwrightScope: full`) reserved for `e2e-acceptance-suite` or manual `npm run test:playwright-ui`.
- One line in `tester.prompt.md` referencing budget.

---

# PHASE 4 — UI/UX per-screen checklist (agents)

**Goal:** Every frontend/test slice must verify **each screen and meaningful UI state** with at least one screenshot and a structured craft checklist before `SLICE_DONE` / `BROWSER_TEST_PASS`.

**Authoritative references (do not duplicate — link and inject):**

- `ai-harness/docs/ui-visual-verification.md` — contrast, padding, viewports
- `docs/ui-ux/04-design-tokens.md` §3.2.1, §5.1
- `docs/ui-ux/00-production-ui-quality-bar.md`
- `ai-harness/skills/frontend-design/SKILL.md`
- `ai-harness/skills/design-craft-notion/SKILL.md`
- `ai-harness/skills/ui-ux-testing/SKILL.md`

## 4.1 Implementer agent — per-screen UI/UX checklist

**Files:** `ai-harness/agents/implementer.prompt.md`, `build-prompt.sh`, optionally `ai-harness/docs/ui-visual-verification.md` (cross-link only)

Update **Browser verification** section in `implementer.prompt.md`:

### Coverage rule

For **every route, page, modal, drawer, or distinct outcome state** created or modified in this slice:

1. Capture **at least one screenshot** per screen/state (more when layout differs by viewport).
2. Required viewports:
   - **320×568** — student mobile routes, mobile auth
   - **1280×720** — desktop instructor, admin, auth split-panel
3. Save under: `ai-harness/generated/runs/screenshots/<slice-id>/implementer/`
4. Filename: `<UTC-timestamp>-<route-or-state-slug>-<viewport>.png`

**Screen/state examples** (capture each that exists in slice):

- List page (default)
- List page with filters/search applied
- Empty state
- Create form
- Edit form
- Inline field error / validation state
- Success toast or post-submit list row
- Forbidden / denied state (wrong role)
- Modal open (edit dialog, confirm dialog, permission guide)
- Distinct outcome panels (Present, ExpiredQr, etc.) when slice touches check-in

### Per-screenshot self-critique checklist

After each capture, verify in the screenshot (not snapshot-only):

| # | Check | FAIL if |
|---|--------|---------|
| 1 | Primary CTA contrast | Label washed out on primary background |
| 2 | Secondary/outline/ghost | Text indistinguishable from page background |
| 3 | Disabled buttons | Illegible label (< 3:1) or looks enabled |
| 4 | Button padding | Cramped label, insufficient inset |
| 5 | Stacked actions | Primary/secondary touching, no gap |
| 6 | Cards/tables | Content flush to edges, no inset padding |
| 7 | Danger actions | Poor contrast on destructive buttons |
| 8 | Listing toolbars | Missing search/filter/sort/pagination on collection views (§14) |
| 9 | Typography | Vietnamese copy clipped, truncated headings |
| 10 | Focus/active nav | Wrong sidebar highlight for current route (BR-14a) |

Any FAIL → fix code → re-screenshot before `SLICE_DONE`.

### Progress evidence (required)

Append to `ai-harness/state/progress.md`:

```
<timestamp> | <slice-id> | browser_verified: <flows> — ui_checklist: <N screens/states> — screenshots: <comma-separated paths> (320w + desktop where applicable)
```

### Harness gate

Optional: add `check-ui-screenshot-evidence.sh` that verifies implementer screenshot dir has ≥1 file per declared route in slice `completionArtifacts` (heuristic: count png files ≥ number of top-level routes under artifact path). Wire as **warn-only** first, not blocking — or blocking for `agent: frontend` only after dry-run.

---

## 4.2 Browser tester agent — per-screen UI/UX audit

**Files:** `ai-harness/agents/tester.prompt.md`, `ai-harness/docs/ui-visual-verification.md`, `ux-bug-logging.md`

In **Full verification phase** of `tester.prompt.md`, add explicit **UI/UX screen audit** after functional cases:

1. Enumerate every **screen/state** exercised in this run (from test cases + slice `completionArtifacts`).
2. For each, capture screenshot to `ai-harness/generated/runs/screenshots/<slice-id>/browser-test/`.
3. Run the same 10-item checklist from `ui-visual-verification.md` on each screenshot.
4. Log defects as `UX-<slice-id>-NNN` per `ux-bug-logging.md`:
   - P0/P1 — contrast failures, illegible disabled states, missing forbidden chrome, broken touch targets
   - P2/P3 — spacing, breadcrumb wayfinding, minor alignment
5. Include in browser test report JSON: `uiScreensAudited: [{ "screen": "/admin/users", "screenshot": "...", "checklistPass": true|false, "failedChecks": [1,4] }]`

**Minimum:** at least **1 screenshot per distinct screen/state** verified in full phase (not only retry phase).

Retry phase: skip UX audit (unchanged).

---

## 4.3 Reviewer agent — UI evidence check

**Files:** `ai-harness/agents/reviewer.prompt.md`

Add checklist item for `frontend` / `test` slices:

- Confirm bundled evidence includes implementer screenshots under `screenshots/<slice-id>/implementer/` covering each modified route/state.
- Spot-check 2–3 screenshots against `ui-visual-verification.md` table (contrast, padding) — read image paths from progress note or bundled artifact list; do not re-run browser.
- If browser test passed but P1 UX bugs logged, `REVIEW_FAIL` only for P0/P1 UX on critical flows; P2/P3 are notes.

---

## 4.4 Shared screen manifest (optional, recommended)

**Files:** NEW `ai-harness/schemas/ui-screen-manifest.schema.json`, helper in `build-prompt.sh`

For frontend slices, inject `{{UI_SCREENS_TO_VERIFY}}` built from:

- Routes under `completionArtifacts`
- Known states from generated test cases (`layer: browser`)
- Slice description keywords (list, form, import, forbidden)

Example injected block:

```markdown
## UI screens/states to verify (screenshot each)

- /admin/users — list default (desktop + mobile)
- /admin/users — create form
- /admin/users — duplicate ID field error
- /admin/users — student forbidden
- /admin/users/import — preview table (if in completionArtifacts)
```

---

# Implementation constraints

- Match bash style in `ai-harness/scripts/lib/common.sh` (`set -euo pipefail`, `source common.sh`, `aih_*` helpers).
- Minimal focused diffs; no drive-by refactors.
- `AIH_CHECK_PROFILE` unset = full gate behavior.
- `chmod +x` on new `.sh` scripts.
- Update `ai-harness/README.md` with new commands and rerun workflow.

---

# Verification (run after implementation)

```bash
cd /Users/trungtran/MyPlace/Personal/Learning/ai-engineering-learning/projects/ai-harnessed_we-check-app

./ai-harness/scripts/check-slice-scope.sh web-admin-users
AIH_CHECK_PROFILE=fast npm run aih:check -- web-admin-users
npm run aih:status

# Full pre-rerun workflow
npm run aih:testgen:drift
npm run aih:testgen:loop
npm run aih:loop
```

**Success criteria:**

- [ ] `web-admin-users` fast check runs one playwright spec, not 126 tests
- [ ] `check-slice-scope.sh` rejects out-of-slice file changes
- [ ] Doc drift alone does not reset `passes` until TestGen regenerates artifact
- [ ] `ralph-once` runs scope gate before browser test
- [ ] `testCaseGate.mode` is `required`
- [ ] `aih:status` runs without error
- [ ] Implementer prompt requires per-screen screenshot + 10-item UI checklist
- [ ] Tester prompt requires per-screen UX audit in full phase with `uiScreensAudited` in report
- [ ] Reviewer prompt checks UI screenshot evidence for frontend slices
- [ ] README documents full rerun workflow

---

# Deliverables

At completion, report:

1. List of all files changed
2. New npm scripts added
3. Exact commands to drain backlog from scratch
4. Any items deferred and why

Implement all phases in one pass.
