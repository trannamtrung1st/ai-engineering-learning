# Implementation plan crosswalk (proposal §19)

Maps each proposal §19 step to owning plan item(s). Parity is verified at item **1.6**
sign-off.

## Phase 1 — Full schema migration

| Step | Description | Plan item(s) |
| --- | --- | --- |
| 1 | Bump run-store schema version | 1.1.1 |
| 2 | Add `paused` | 1.1.2 |
| 3 | Add structured stop records | 1.1.2 |
| 4 | Add lifecycle invariants | 1.1.1, 1.1.2 |
| 5 | Limit exhaustion → pause | 1.1.2 |
| 6 | `review_incomplete` → pause | 1.1.2, 1.3.2 |
| 7 | User cancellation → pause | 1.1.2, 1.3.3 |
| 8 | Remove legacy resume restoration | 1.6 (this item) |
| 9 | Update fixtures; delete old runs | 1.6, 1.1.1 |

## Phase 2 — Configuration and digest migration

| Step | Description | Plan item(s) |
| --- | --- | --- |
| 1 | Replace monolithic config digest | 1.2.1 |
| 2 | Add `config_contract` | 1.2.1 |
| 3 | Add `config_execution` | 1.2.1 |
| 4 | Rebind approvals to `config_contract` | 1.2.1 |
| 5 | Execution-policy allowlist | 1.2.2 |
| 6 | Resolve candidate config during resume | 1.2.2, 1.3.1 |
| 7 | `--set` on `tdp resume` | 1.3.3 |
| 8 | Atomic accepted-config persistence | 1.2.3 |

## Phase 3 — Pure resume planning

| Step | Description | Plan item(s) |
| --- | --- | --- |
| 1 | Immutable `ResumePlan` | 1.3.1 |
| 2 | `prepare_resume()` | 1.3.1 |
| 3 | Stop-specific validators | 1.3.2 |
| 4 | `apply_resume_plan_atomically()` | 1.3.2 |
| 5 | `--check` | 1.3.3 |
| 6 | Structured CLI diagnostics | 1.3.3 |
| 7 | Run lease / ownership | 1.3.4 |

## Phase 4 — Session-binding migration

| Step | Description | Plan item(s) |
| --- | --- | --- |
| 1 | Session bindings replace raw IDs | 1.4.1 |
| 2 | `session_instance_id` | 1.4.1 |
| 3 | Generation and binding state | 1.4.1 |
| 4 | No transient pending Cursor IDs | 1.4.2 |
| 5 | Capabilities bound to session identity | 1.4.2 |
| 6 | Session-lineage persistence | 1.4.3 |

## Phase 5 — Provider recovery

| Step | Description | Plan item(s) |
| --- | --- | --- |
| 1 | `ProviderSessionNotFoundError` | 1.5.1 |
| 2 | Cursor not-found classification | 1.5.1 |
| 3 | Role-specific recovery manifests | 1.5.2 |
| 4 | Resume-then-replace | 1.5.2 |
| 5 | Provider-ID binding transition | 1.5.2 |
| 6 | One-replacement-per-action | 1.5.3 |
| 7 | `phase_action_id` idempotency | 1.1.2, 1.5.3 |
