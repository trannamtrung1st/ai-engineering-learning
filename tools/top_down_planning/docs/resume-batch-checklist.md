# Resume batch deployment checklist (proposal §6.1)

Coordinated delivery for run-store schema v3 and split configuration digests. Items
**1.1.1**, **1.1.2**, **1.1.3**, and **1.2.1** must land together — no dual
`digests.config` read/write in production code.

## Pre-merge

1. Confirm `CURRENT_RUN_SCHEMA_VERSION` is **3** (`persistence/run_schema.py`).
2. Confirm new runs persist `digests.config_contract` and `digests.config_execution`
   (not monolithic `digests.config`).
3. Confirm lifecycle fields on create: `status`, `stop`, `phase_action_id`,
   `session_replacement_phase_action_id`, `phase_action_domain_committed_id`.
4. Run unit gate tests:
   - `pytest tests/unit/test_run_schema_version.py` (§21 test 42 — old schema rejected)
   - `pytest tests/unit/test_no_monolithic_config_digest.py` (no `digests.config` in src)
   - `pytest tests/unit/test_run_lifecycle.py`
   - `pytest tests/unit/test_resume_config_policy.py`

## Merge order

1. **1.1.1** — schema version bump and rejection of unsupported versions.
2. **1.1.2** — `paused` / `failed` / `completed` lifecycle, structured `stop`, limit
   exhaustion → `paused` (not `rejected`/`blocked`).
3. **1.1.3** — split digests (`config_contract`, `config_execution`), approval rebind.
4. **1.2.1** — resume policy allowlist, candidate config resolution, atomic config commit.

Downstream phases (3–5) depend on this batch but may merge after it is green.

## Post-merge operator verification

1. Delete interim **schema v2** development runs (no migrator — recreate if needed).
2. `tdp run --config <yaml>` — confirm `schema_version: 3` in `run.json`.
3. Exhaust a limit → confirm `status: paused`, `stop.code: limit_exhausted`.
4. `tdp resume --run <id> --set limits.<phase>.<limit>=<N> --check` — no writes.
5. `tdp resume --run <id> --set limits.<phase>.<limit>=<N>` — `resume_applied` event,
   consumed counters unchanged.
6. `tdp status --run <id>` — shows `config_contract` / `config_execution` digests and
   `stop` when paused.

## CI guards

- `test_no_monolithic_config_digest.py` — fails if production code reads/writes
  `digests.config`.
- `test_run_schema_version.py::test_unsupported_schema_version_rejected_with_recreate_message`
  — §21 test 42.
