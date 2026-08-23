# Top Down Planning documentation

Top Down Planning (`tdp`) orchestrates planning and production: it takes an input and output goal, builds a top-down plan, reviews and validates that plan, produces output in coherent batches, and resolves a final quality outcome.

This directory is the publication-ready documentation set. The [package README](../README.md) remains the in-repo operator entry; these pages expand it for newcomers, operators, runtime agents, and maintainers.

Production runs use the `cursor` provider. The `stub` provider is test-only. Host IDE planning modes are not part of the TDP workflow. Resume locking and the Cursor adapter require a POSIX environment; desktop alerts need the optional `[notifications]` extra. Details: [install](manual/install.md) and [quality checks](QUALITY-CHECKS.md).

Shared vocabulary lives in [lifecycle terms](concepts/lifecycle-terms.md) (`status` vs `phase` vs review `active_stage` vs revisions). Duplicate explanations elsewhere point back to one canonical page.

## Choose a path

| Audience | Start here |
| --- | --- |
| Newcomer | [Concepts overview](concepts/overview.md), then [install](manual/install.md) and the [first-run walkthrough](workflows/first-run.md) |
| Operator | [Operator manual](manual/README.md) and [operational workflows](workflows/README.md) |
| Runtime agent | **[Start here: agent documentation hub](agents/README.md#start-here)** |
| Maintainer | [Architecture](architecture/README.md), [internals](internals/README.md), and [design decisions](decisions/README.md) |

## Contents

Every major section produced by the detailed documentation items:

### Concepts

- [Concepts index](concepts/README.md)
- [Overview](concepts/overview.md)
- [Plan tree](concepts/plan-tree.md)
- [Quality loop](concepts/quality-loop.md)
- [Lifecycle terms](concepts/lifecycle-terms.md)
- [Roles](concepts/roles.md)

### Workflows

- [Workflows index](workflows/README.md)
- [First run](workflows/first-run.md)
- [Lifecycle](workflows/lifecycle.md)
- [Operations](workflows/operations.md)
- [Prepared execution and Sub-TDPs](workflows/prepared-and-sub-tdp.md)
- [Agent sessions](workflows/agent-sessions.md)

### Operator manual

- [Manual index](manual/README.md)
- [Install and setup](manual/install.md)
- [User CLI](manual/cli.md)
- [Configuration](manual/configuration.md)
- [Run store](manual/run-store.md)
- [Observability](manual/observability.md)
- [Troubleshooting](manual/troubleshooting.md)

### Runtime agents

- [Agent hub](agents/README.md)
- [Protocol](agents/protocol.md)
- [Planner](agents/planner.md)
- [Producer](agents/producer.md)
- [Reviewer](agents/reviewer.md)
- [Agent CLI, schemas, and authorization](agents/cli.md)
- [Agent troubleshooting](agents/troubleshooting.md)

### Architecture, internals, decisions

- [Architecture index](architecture/README.md) — [system context](architecture/system-context.md), [lifecycle](architecture/lifecycle.md), [domain](architecture/domain.md), [sessions](architecture/sessions.md)
- [Internals index](internals/README.md) — [config and snapshots](internals/config-and-snapshots.md), [persistence](internals/persistence.md), [reviews](internals/reviews.md), [packages](internals/packages-and-sub-tdp.md), [security](internals/security.md), [maintenance](internals/maintenance.md)
- [Design decisions index](decisions/README.md) — [stop states](decisions/lifecycle-stop-states.md), [split digests](decisions/split-config-digests.md), [session bindings](decisions/session-bindings.md), [run ownership](decisions/run-ownership.md), [agent authorization](decisions/agent-authorization.md), [prepared-execution integrity](decisions/prepared-execution-integrity.md)

Operator troubleshooting (cancellation, concurrency, diagnosis, recovery) lives under the [operator manual](manual/troubleshooting.md), not as a separate landing section. Runtime-agent errors stay on the [agent hub](agents/README.md) and [agent troubleshooting](agents/troubleshooting.md) pages.

## Newcomer path

Follow these pages in order. Command flags and recovery details stay on the linked manual pages rather than being restated here.

1. Prerequisites, installation, `cursor` provider setup, POSIX limits, optional `[notifications]`, and a minimal config — [Install and setup](manual/install.md)
2. Confirm `tdp --help` / `tdp agent help`, start a run from the example YAML — [First run](workflows/first-run.md) (steps 1–2)
3. Inspect `status` and `phase` — [First run](workflows/first-run.md) (step 3) and [lifecycle terms](concepts/lifecycle-terms.md)
4. After a default `tdp run` (`--until plan`), continue with `tdp resume --until completed` — [First run](workflows/first-run.md) (step 4). Omit `--until` on resume to advance one orchestrator step only — [operations](workflows/operations.md)
5. Interpret `completed`/`accepted` vs paused vs failed — [First run](workflows/first-run.md) (step 5) and [lifecycle](workflows/lifecycle.md)

## Runtime agents start-here

Inside a provider session, skip the operator walkthrough. From this landing page:

1. Open the [agent hub start-here list](agents/README.md#start-here)
2. Shared rules: [protocol](agents/protocol.md) (request files, revision safety, completion signals)
3. Exact contracts: [agent CLI, schemas, and authorization](agents/cli.md) (`tdp agent schema` / `tdp agent example`; no `--role`)
4. Role pages: [planner](agents/planner.md), [producer](agents/producer.md), [reviewer](agents/reviewer.md)
5. Errors: [agent troubleshooting](agents/troubleshooting.md)

Then `tdp agent help` and `tdp agent readme` in the session. Packaged role skills are auto-injected when `agent_context.bundled_skills` is true (default).

## Canonical homes

| Topic | Canonical page |
| --- | --- |
| Install and provider setup | [manual/install.md](manual/install.md) |
| Recovery and diagnosis | [manual/troubleshooting.md](manual/troubleshooting.md) |
| Lifecycle vocabulary | [concepts/lifecycle-terms.md](concepts/lifecycle-terms.md) |
| Agent protocol and schemas | [agents/](agents/README.md) |
| Enduring design rationale | [decisions/](decisions/README.md) |

`Sub-TDP` is the parent/child execution feature; `sub_tdps` is the run **phase** name. `tdp sub-tdp attach` is the operator command.

## About these docs

- [Page ownership](PAGE-OWNERSHIP.md) names every planned page, its audience job, and which plan item fills it.
- [Quality checks](QUALITY-CHECKS.md) records the link scan and command/config verification evidence for this set.

Links in this set are repository-relative so the docs remain browsable on GitHub.
