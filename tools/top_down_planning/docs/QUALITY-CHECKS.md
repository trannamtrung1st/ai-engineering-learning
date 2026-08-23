# Documentation quality checks

**Audience:** document authors and reviewers verifying this documentation set.

**Purpose:** hold the recorded evidence that the docs set is navigable and that command and configuration claims match current public behavior.

**Owned topics:** complete Markdown link scan under `tools/top_down_planning/docs/`, resolution of intended repository-path and relative-link references, targeted comparisons of documented commands and configuration against CLI help, schemas, or tests, and checks that examples label `cursor` versus test-only `stub` and call out POSIX/platform and optional-dependency limits.

Recorded during final integration (`item-971d08d48ab3`). Unfinished-work markers do not remain under `tools/top_down_planning/docs/`.

Landing: [README.md](README.md). Page map: [PAGE-OWNERSHIP.md](PAGE-OWNERSHIP.md).

## Method

Optional link checkers (`lychee`, `markdown-link-check`) are not installed in this environment. The equivalent local check:

1. Enumerate all 48 Markdown files under `tools/top_down_planning/docs/`.
2. Resolve every repository-relative Markdown link (bracket label plus parenthesized relative path) and same-file/other-file heading fragment (`#slug` from ATX headings).
3. Confirm the landing page links every page in that tree.
4. Compare documented user and agent commands against `tdp --help`, per-command `--help`, `tdp agent help`, `tdp agent schema`, and `tdp agent example`.
5. Compare documented config keys against `tdp agent schema config` and `tools/top_down_planning/examples/top-down-planning.yaml`.
6. Search the tree for `cursor` / `stub` labeling and POSIX / `[notifications]` callouts.

Backticked strings that are **not** navigable files (CLI commands, YAML keys, glob patterns such as `docs/**`, maintainer module paths like `domain/run_lifecycle.py`, lock sentinels `.resume.lock.d/.owner.lock`) are citations of current behavior, not Markdown links. Repo-root skill paths cited from internals (`.cursor/skills/tools-dev/SKILL.md`, `.cursor/skills/tdd/SKILL.md`) exist at the repository root.

## Markdown link scan

| Check | Result |
| --- | --- |
| Files scanned | 48 |
| Markdown links resolved | 526 |
| Broken files or heading fragments | **0** |
| Landing links to every docs page | **yes** (including this page and [PAGE-OWNERSHIP.md](PAGE-OWNERSHIP.md)) |
| External `http(s)` links in this tree | **0** |
| Unfinished-work markers | **none** |

Intended example and package paths used as Markdown links from docs (for example `../README.md`, `../../examples/top-down-planning.yaml`) resolve.

## Command and configuration comparisons

Compared against live `tdp` help and published schemas (not against unpublished proposal text). Help strings that mention a “proposal” section are implementation provenance only.

### User CLI (`tdp --help` and per-command `--help`)

Documented on [user CLI](manual/cli.md). Matches:

| Claim in docs | Public evidence |
| --- | --- |
| Subcommands `run`, `prepare`, `execute`, `resume`, `status`, `inspect`, `validate`, `doctor`, `sub-tdp`, `agent` | `tdp --help` |
| `tdp run --until {plan,validated,completed}` and `--force` | `tdp run --help` (choices only; does not print the default) |
| `tdp run --until` **defaults to `plan`** | argparse `default="plan"` in `cli/main.py`; [package README](../README.md) |
| `prepare --output`, `--replace`, `--planning-run` | `tdp prepare --help` |
| `execute --manifest` required; `--unit`, `--parent-only`, `--upstream UNIT=RUN_ID`, `--baseline RUN_ID` | `tdp execute --help` |
| `resume --check`, `--allow-config-drift`, `--until`; omit `--until` = one orchestrator step (not the `tdp run` default) | `tdp resume --help` |
| `inspect --view {active,audit}` (default `active`) | `tdp inspect --help` |
| `doctor --fix`; omit `--run` for workspace diagnostics | `tdp doctor --help` |
| `sub-tdp attach --parent` and `--child` required | `tdp sub-tdp attach --help` |
| `run` / `prepare` / `execute`: `--runs-dir` > `$TDP_RUNS_DIR` > `runtime.runs_dir`; **no** `./runs` fallback | those commands’ `--help` |
| `resume` / `status` / `inspect` / `validate` / `doctor` / `sub-tdp attach`: same precedence **plus** `./runs` | those commands’ `--help` |
| Presentation flags (`--stream-json`, `--log-level`, `--no-notify`, …) on mutating user commands; `status` / `inspect` / `validate` / `doctor` / `sub-tdp attach` omit `--no-notify` | per-command `--help`; [observability](manual/observability.md) |

### Agent CLI (`tdp agent help`, `tdp agent --help`, `tdp agent review --help`)

Documented on [agent CLI](agents/cli.md). Matches: `help`, `readme`, `schema`, `example`, `plan`, `production`, `review`, `run`; review subcommands `respond`, `request`, `record-actions`. Mutating-request schema names and the example list on that page match `tdp agent schema` / `tdp agent example` (23 schemas including `config`, `agent-error`, and `*-response`; 22 examples). Authorization: no `--role`; token from `TDP_CAPABILITY_TOKEN_FILE` — [agent-authorization decision](decisions/agent-authorization.md).

### Configuration

Documented on [configuration](manual/configuration.md). Matches `tdp agent schema config` top-level keys: `agent_context`, `context_snapshot`, `execution`, `limits`, `notifications`, `observability`, `planning`, `project`, `provider`, `review`, `run`, `runtime`, `version`. `provider.name` enum is `cursor` \| `stub`. `execution.mode` exists. `limits.provider.turn_idle_timeout_seconds`, `max_retries_per_call`, and `max_stream_json_record_bytes` exist; example YAML sets idle timeout default `2` and stream-json line cap default `1048576`. Resume hatch `--allow-config-drift` before vs after whole-plan approval matches `tdp resume --help`.

### Resume approval bindings (HEAD)

Compared against `domain/approval_digests.py` and `orchestrator/prepare_resume.py` (`_approval_binding_valid`):

| Claim in docs | Public evidence |
| --- | --- |
| Plan approval keys: `plan`, `config_contract`, `input`, `output_goal`, `context_spec` | `PLAN_APPROVAL_DIGEST_KEYS` |
| Whole-output approval (when present and approved) adds `output` and `context_snapshot` | `OUTPUT_APPROVAL_DIGEST_KEYS` |
| Pending `whole_output` loop does not require output snapshot keys on the **plan** approval | `find_whole_output_approval` is `None` → return after plan-key match |
| Pages: [operations](workflows/operations.md), [configuration](manual/configuration.md#resume-and-drift), [split-digest decision](decisions/split-config-digests.md), [reviews internals](internals/reviews.md), [config/snapshots](internals/config-and-snapshots.md) | this revision |

### Stream-json cap, leftover teardown, and capability reuse (HEAD)

Compared against `core_tools` Cursor stream-json / process-cleanup tests and `tests/unit/test_reviewer_capability_stream_rebind.py`:

| Claim in docs | Public evidence |
| --- | --- |
| Assembled line cap includes newline; TDP default `1048576` | `limits.provider.max_stream_json_record_bytes`; `test_stream_json_record_limit.py` |
| Cap independent of read/exit; drain stops at cap; valid prefix then oversized rejection; flood writers must not remain on argv | `test_exiting_oversized_flood_does_not_buffer_past_rescue_slack`; `test_oversized_record_after_several_valid_records_is_rejected`; `test_rejected_oversized_flood_does_not_leave_a_blocked_writer` |
| Cap rejection kills leftover writers when bound terminate fails closed or identity inspect is unverifiable; live-match kills use verified identity | `test_oversized_writer_is_killed_when_bound_terminate_fails_closed`; `test_oversized_writer_is_killed_when_identity_inspect_is_unverifiable` |
| Leftover teardown fails on the original leak; scans ignore Linux `TASK_DEAD` and Linux/Darwin zombies; pre-run orphan cleanup ignores unrelated macOS hosts; janitor wait at status-read and `raw_wait` | `test_injected_orphan_fails_leftover_detector_then_is_reaped`; `test_leftover_scan_ignores_linux_dead_x_state`; `test_continue_run_preflight_ignores_unrelated_host_pids`; `test_wait_deducts_status_read_from_one_deadline` |
| Stream-event sync reuses the live exported capability token; no mint per event | `test_reviewer_turn_drain_does_not_mint_capability_per_stream_event` |
| Pages: [sessions](architecture/sessions.md), [security](internals/security.md), [troubleshooting](manual/troubleshooting.md), [agent-authorization](decisions/agent-authorization.md) | this revision |

## `cursor` versus `stub`

| Location | Labeling |
| --- | --- |
| Landing, [overview](concepts/overview.md), [roles](concepts/roles.md) | `cursor` for production; `stub` test-only; host IDE modes out of scope |
| [Install](manual/install.md), [first run](workflows/first-run.md), [workflows index](workflows/README.md), [manual index](manual/README.md), [configuration](manual/configuration.md) | Same; first-run is not a `stub` walkthrough |
| [Security internals](internals/security.md) | `stub` provider: tests only |

Example YAML comments (outside this tree) also mark `stub` as scripted-test-only. Docs examples use `provider.name: cursor`.

## POSIX, Windows, and optional dependencies

| Limit | Where documented |
| --- | --- |
| POSIX `fcntl` flock required for multi-process resume locking; Windows Python not supported for that lock | [install](manual/install.md), [troubleshooting](manual/troubleshooting.md), [run ownership](decisions/run-ownership.md), [security](internals/security.md) |
| `CursorProvider` fails fast on Windows | [install](manual/install.md), [system context](architecture/system-context.md), [sessions](architecture/sessions.md) |
| Optional extra `[notifications]` (`notify-py`); without it, desktop alerts are silently skipped; `CI=true` and headless Linux suppress sends | [install](manual/install.md), [observability](manual/observability.md), [troubleshooting](manual/troubleshooting.md), [security](internals/security.md) |
| Landing restates POSIX + optional notifications and points here | [README.md](README.md) |

## Navigation after integration

- [Landing](README.md) has audience entry points, a full contents list, a five-step newcomer path (install → first run → inspect → resume → interpret), and a runtime-agent start-here path to protocol, schemas/authorization, role pages, and troubleshooting.
- Canonical homes (install, troubleshooting, lifecycle terms, agents, decisions) are listed on the landing and in [PAGE-OWNERSHIP.md](PAGE-OWNERSHIP.md).
- Section indexes link back to the landing. [Install](manual/install.md) sends newcomers to [first run](workflows/first-run.md).
