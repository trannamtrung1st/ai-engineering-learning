# Agent CLI, schemas, and authorization

**Audience:** runtime agents discovering exact request shapes and authorization rules.

Prefer `tdp agent help`, `tdp agent readme`, `tdp agent schema`, and `tdp agent example` as the source of exact names. This page indexes those contracts. User-facing `tdp run` / `tdp resume` commands are in the [operator manual](../manual/cli.md), not here.

## Discoverability

```bash
tdp agent help
tdp agent readme
tdp agent schema            # list
tdp agent schema <name>     # one schema
tdp agent example           # list
tdp agent example <name>    # one example
tdp agent run status --run <run-id>
```

Authorization is session-bound. Do not pass `--role`. Mutating commands require the capability token from `TDP_CAPABILITY_TOKEN_FILE`. Read-only discoverability commands do not.

Agent commands use `--runs-dir`, `$TDP_RUNS_DIR`, or `./runs`. Run ids use `run-YYYYMMDDTHHMMSS-<6hex>` (UTC creation time plus random suffix).

## Command groups

From `tdp agent help`:

**Plan**

- `tdp agent plan snapshot --run <run-id> [--view active|audit|ready|issues|budget]`
- `tdp agent plan apply --run <run-id> --request $TDP_AGENT_REQUESTS_DIR/...`
- `tdp agent plan check --run <run-id> [--mode draft|approval]`

**Production**

- `tdp agent production snapshot --run <run-id> [--view tree|ready|dispositions]`
- `tdp agent production apply --run <run-id> --request ...`
- `tdp agent production check --run <run-id>`
- `tdp agent production request-amendment --run <run-id> --request ...`
- `tdp agent production submit-completion --run <run-id> --request ...`
- `tdp agent production report-blocked --run <run-id> --request ...`

**Review**

- `tdp agent review request --run <run-id> --request ...`
- `tdp agent review respond --run <run-id> --request ...`
- `tdp agent review record-actions --run <run-id> --request ...`

Finding categories: `review_policy.category_definitions` in reviewer packages; `tdp agent readme` (Review finding categories); `tdp agent schema review-respond`. Mandatory reviewers: `rubric_items` and `required_audit_passes` in the review package; built-in `rule_id` list in `tdp agent readme` (Built-in finding-family rule_id values).

## Published schemas and examples

Hub contract list (mutating requests):

| Schema | Purpose |
| --- | --- |
| `plan-transaction` | `plan apply` |
| `production-apply` | `production apply` |
| `review-respond` | `review respond` |
| `review-record-finding-actions` | `review record-actions` |
| `focused-review-request` | `review request` |
| `completion-claim` | `submit-completion` |
| `amendment-request` | `request-amendment` |
| `blocker-report` | `report-blocked` |

Also published (inspect with `tdp agent schema`): `config`, `agent-error`, and the `*-response` schemas for apply/snapshot/check/status/review commands.

Examples (`tdp agent example`): `expand-branch`, `batch-result`, `empty-output`, `evidence-revision`, `evidence-revision-focused`, `review-respond`, `review-respond-focused-with-instance-ref`, `review-respond-family-discovery-focused-plan`, `review-respond-family-discovery-focused-output`, `review-respond-verification`, `review-respond-scope`, `review-respond-family-discovery`, `review-respond-family-discovery-output`, `review-respond-family-verification`, `review-respond-family-verification-output`, `review-record-finding-actions`, `review-record-family-fix`, `review-record-family-fix-output`, `focused-review-request`, `amendment-request`, `completion-claim`, `blocker-report`.

Examples validate against schemas. Copy structure from an example and adapt ids from the session package.

## Authorization and capability tokens

The orchestrator binds one primary planner, producer, or reviewer session per phase.

- Mutating `tdp agent` commands read the session capability token from `TDP_CAPABILITY_TOKEN_FILE` on the provider subprocess that runs the turn.
- Reviewer sessions allocate a provider session id, bind the token, then deliver the review package (or a mandatory `finding_verification` recheck) before the agent may call `tdp agent review respond`.
- Authorization checks phase, allowed operations, the bound provider session, and (for reviewers) the review loop.
- Capability records store only a `secret_hash`; tokens are revoked when turns, loops, or phases end.
- Agents do not pass `--role` on the CLI.

If apply reports `capability_denied`, the token file is missing or the orchestrator has not bound a session capability. Retry the mutating command without caching capability state in the shell.

Request files, revision fields, and completion signals: [protocol](protocol.md). Rationale: [agent-authorization decision](../decisions/agent-authorization.md).
