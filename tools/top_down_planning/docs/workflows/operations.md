# Staged operations, resume, and drift

**Audience:** operators controlling how far a run goes and how it continues.

Diagnosis and safe recovery (orphans, `tdp doctor --fix`, cancel vs failed) are owned by [manual troubleshooting](../manual/troubleshooting.md). This page is the procedure for `--until`, inspect, pause/resume, and configuration drift.

## Staged planning (`--until`)

`tdp run` and `tdp resume` accept `--until {plan,validated,completed}`:

| Target | Meaning (from CLI help) |
| --- | --- |
| `plan` | Through planning construction |
| `validated` | Plan validation (`plan_validated` and beyond on resume) |
| `completed` | Final outcome (`output_validated` or terminal `completed`) |

On `tdp run`, `--until` **defaults to `plan`** (planning construction only). Omitting `--until` is not a full run through production. On `tdp resume`, **omit** `--until` to advance **one** orchestrator step (default). Pass `--until validated` or `--until completed` to continue to a later milestone.

```bash
tdp run --config cfg.yaml --until plan
tdp run --config cfg.yaml --until validated
tdp resume --run <run-id> --until completed --config cfg.yaml
tdp resume --run <run-id> --config cfg.yaml
```

Partial `--until` milestones can notify when notifications are enabled; default single-step resume does not emit `target_reached`. [Observability](../manual/observability.md).

## Status, inspect, validate

```bash
tdp status --run <run-id> --config cfg.yaml
tdp status --run <run-id> --stream-json
tdp inspect --run <run-id> --view active --config cfg.yaml
tdp inspect --run <run-id> --view audit --config cfg.yaml
tdp validate --run <run-id> --config cfg.yaml
```

Use these instead of editing `run.json` / `plan.json` / `production.json`. [Run store](../manual/run-store.md). `validate`, `status`, and `inspect` never send desktop notifications.

## Pause and resume

A run **pauses** with an operational `stop` (Ctrl+C, limits, provider blips, amendment pending, Sub-TDP wait). That is not `status=failed`.

1. `tdp status` — read `stop.code` and `phase`.
2. `tdp resume --check --run <id> --config cfg.yaml` — print the resume plan; **no writes**, no provider calls.
3. `tdp resume --run <id> --config cfg.yaml` — apply and continue (add `--until` if you want a loop).

Failed runs cannot be resumed. Owned Ctrl+C: [troubleshooting](../manual/troubleshooting.md#cancellation). Limit increases must be **strictly greater** than `consumed` when the stop tracks consumption.

## Configuration drift

Resume binds **plan approval** to `plan`, `config_contract`, `input`, `output_goal`, and `context_spec` only. When a **current whole-output approval** exists, resume also binds `output` and `context_snapshot`. A pending `whole_output` loop (no approved output record yet) must **not** require those output snapshot keys on the plan approval. Limits bind to `digests.config_execution`. Presentation (`observability.*`, `notifications.*`, `runtime.runs_dir`) may change without invalidating resume.

By default, resume **rejects** contract drift and non-model context_spec drift. `--allow-config-drift` is a per-invocation hatch:

- Before whole-plan approval, accepted contract and model changes apply and rebind digests.
- After whole-plan approval, approval-bound contract and model changes are ignored with warnings.

Always `--check` first. Exact key sets: [configuration](../manual/configuration.md#resume-and-drift).

Related: [lifecycle](lifecycle.md), [first run](first-run.md).
