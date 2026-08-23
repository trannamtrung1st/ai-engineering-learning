# Persistence and crash recovery

**Audience:** maintainers of the run store and commit path.

Operators inspect with `tdp status` / `inspect` / `validate` / `doctor` — [run store](../manual/run-store.md). Do not hand-edit orchestrator files. Lifecycle commits: [lifecycle architecture](../architecture/lifecycle.md).

## Layout

Under `<runs-root>/<run-id>/` (run id `run-YYYYMMDDTHHMMSS-<6hex>`):

| Name | Kind |
| --- | --- |
| `run.json` | Canonical run (status, phase, outcome, stop, digests, sessions, `schema_version`) |
| `plan.json` | Plan tree |
| `production.json` | Production + Sub-TDP orchestration |
| `events.jsonl` | Append-only audit journal |
| `resolved-config.yaml` | Materialized resolved config |
| `invocation.json` | CLI invocation metadata |
| `reviews/` | Review loop records |
| `artifacts/<snapshot-uuid>/` | Immutable evidence snapshots |
| `capabilities/` + `capability/` | Capability records and current token file |
| `agent-requests/` | Non-canonical agent payloads |
| `.resume.lock.d/.owner.lock` | Persistent flock sentinel (never unlinked during release) |

Run `schema_version` is currently 3. Unsupported or missing version fails load; there is no automatic migrator. Config document `version` is unrelated.

The run directory and listed children must not be symlinks. Paths must stay under the store root and the run directory (`path_containment`).

## Revisions and compare-and-swap

`CommitSpec` carries optional new payloads plus **expected** revisions:

- `run_expected_revision`
- `plan_expected_revision`
- `production_expected_revision`
- `review_expected_revisions` (per review id)

A mismatch is a CAS conflict (`revision_conflict` at the agent tool). Agent apply uses `base_revision` / `production_revision` from snapshots.

## Journaling and atomic commits

Each commit appends zero or more events. Journaled events carry `txn_id`, `event_index`, and `event_count` for crash-safe recovery. Known transaction statuses: `prepared`, `replacing`, `appending_events`, `committed`.

File kinds in the journal: `run`, `plan`, `production`, `resolved_config`, `invocation`, `review`, `artifact`. Artifact bytes (`StagedArtifact`) are promoted only when the transaction commits.

Lifecycle transition + required audit event share one `CommitSpec`. Observability/notification mirrors consume the same events.

An `agent_request_read` without matching `agent_request_completed` means the process died after consuming the request file. Request audit is append-only and is **not** rolled back when the domain commit fails.

## Crash recovery

On open, the store recovers incomplete journals from the recorded status (restore backups vs finish replace vs finish event append). Leftover `.creating-*` staging directories are hygiene issues (`tdp doctor --fix` removes them). Tests for mid-`Path.replace` faults live under `tests/unit/test_commit_crash_recovery.py`.

Inspection surfaces: `tdp inspect --view active|audit`, `tdp doctor`, `events.jsonl`. Transaction inspect helpers exist for maintainers; they are not a second operator API.

Related: [run ownership](../decisions/run-ownership.md), [security](security.md).
