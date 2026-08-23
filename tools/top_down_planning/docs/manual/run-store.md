# Run store

**Audience:** operators inspecting what a run wrote.

Each run lives under `<runs-root>/<run-id>/`. Run ids look like `run-YYYYMMDDTHHMMSS-<6hex>`. Locate the store with `--runs-dir`, `$TDP_RUNS_DIR`, or `runtime.runs_dir` ([CLI](cli.md#run-store-location)).

**Do not hand-edit orchestrator-owned files.** Inspect with `tdp status`, `tdp inspect`, `tdp validate`, `tdp doctor`, and `tdp agent run status`. Persistence layout for maintainers: [persistence](../internals/persistence.md).

## Operator-visible artifacts

| Path | What it is |
| --- | --- |
| `run.json` | Canonical run record: `status`, `phase`, `outcome`, `stop`, digests, sessions |
| `plan.json` | Plan tree and plan revision |
| `production.json` | Batches, dispositions, evidence, completion claim, Sub-TDP orchestration |
| `events.jsonl` | Append-only orchestration audit log (no agent prose) |
| `resolved-config.yaml` | Materialized resolved configuration |
| `invocation.json` | CLI invocation metadata (presentation/transport), not semantic config |
| `agent-requests/` | Agent-authored request files (debug/postmortem; not required for resume) |
| `agent-transcript.jsonl` | Optional redacted provider transcript (`--agent-transcript`) |
| `artifacts/` | Immutable captured production evidence snapshots |

Capability tokens live under a capability directory for the active session. Treat exported run directories as potentially sensitive (request payloads and transcripts).

## How to inspect

```bash
tdp status --run <run-id> --config cfg.yaml
tdp status --run <run-id> --stream-json
tdp inspect --run <run-id> --view active --config cfg.yaml
tdp inspect --run <run-id> --view audit --config cfg.yaml
tdp validate --run <run-id> --config cfg.yaml
tdp doctor --run <run-id> --config cfg.yaml
tdp agent run status --run <run-id>
```

`inspect --view active` is the default. `audit` includes inactive history. `validate` runs deterministic plan/output validators. `doctor` reports hygiene and orphan agent pids; `--fix` is state-changing ([CLI](cli.md)).

Sub-TDP parent state is under `production.json` → `sub_tdps`. Attach and resume through documented commands, not by editing that object.

Related: [lifecycle terms](../concepts/lifecycle-terms.md), [troubleshooting](troubleshooting.md), [observability](observability.md).
