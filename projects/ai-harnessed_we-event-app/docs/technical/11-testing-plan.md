# Testing Plan

## 1. Test Strategy
Use a layered strategy:
- Unit tests for rule validators and state transition guards.
- Integration tests for transactional module behavior.
- End-to-end scenario tests for full workflow acceptance.

Priority is correctness of business invariants over UI polish in this phase.

## 2. Test Pyramid
- Unit: 60%
- Integration: 30%
- End-to-end: 10%

## 3. Core Scenario Matrix
| Scenario | Expected Result | Traceability |
|---|---|---|
| Register with available seat | `Registered` | AC-01, BR-03 |
| Register when full + waitlist enabled | `Waitlisted` | AC-02, BR-04 |
| Duplicate registration attempt | blocked | AC-03, BR-01 |
| Capacity under heavy concurrent requests | never exceeds capacity | AC-04, BR-03 |
| In-window check-in | check-in stored with timestamp | AC-05, BR-10, BR-13 |
| Out-of-window check-in | rejected with code | AC-06, BR-10 |
| Event completion attendance finalization | `Attended`/`Absent` correct | AC-07, BR-12 |
| Feedback in allowed window | accepted | AC-08, BR-15 |
| Eligibility evaluation pass/fail | deterministic with reason | AC-09, BR-17..BR-19 |
| Organizer views eligible list | list + reasons available | AC-10 |
| Critical config change audit | audit record persisted | AC-11, BR-22 |
| Status history retrieval | transitions traceable | AC-12 |
| Events list page 2 | correct slice + total | AC-13 |
| Registrations list beyond capacity | never returns more than `pageSize` items | AC-13, NFR-16 |
| Audit logs paginated | ordered + total count | AC-13 |
| My registrations paginated | single API call, no N+1 fan-out | AC-14, FR-29 |

## 4. Unit Test Coverage Targets
- registration dedupe validator
- capacity guard validator
- check-in window validator
- feedback submission validator
- eligibility rule evaluator
- state transition guard functions

## 5. Integration Test Coverage Targets
- registration + waitlist promotion atomicity
- cancellation deadline policy behavior
- check-in + registration state consistency
- eligibility persistence with reason
- audit write for critical config changes
- paginated list queries return correct `total` and page boundaries

## 6. End-to-End Flows
Flow A:
- draft -> publish -> open registration -> register -> check-in -> feedback -> eligibility

Flow B:
- full event -> waitlist entry -> cancellation -> auto promotion -> check-in

Flow C:
- admin critical rule change after registration open -> audit verification

## 7. Deterministic Test Controls
- Fixed clock abstraction for all time-window tests.
- Transaction rollback or database reset per test.
- Seeded deterministic fixture IDs where practical.

## 8. Validation and Guardrail Gates (Local)
Minimum pre-merge gates (enforced by `npm run aih:check` / `run-checks.sh`):

- `npm run test:unit` — all unit and component tests pass (workspaces that define `test:unit`)
- `npm run test:integration` — all integration tests pass (requires Postgres via `npm run aih:dev:db:up`)
- `npm run test:e2e` — API scenario acceptance suite passes
- slice `testRequirements` artifacts exist when defined in backlog
- `typecheck`, `lint`, `build` pass across workspaces
- no unresolved canonical-state naming drift
- no missing audit event for critical operations

Frontend/test slices: implementer uses Playwright MCP for interactive browser smoke verification (see `ai-harness/docs/browser-mcp.md`). A dedicated **browser test agent** gate (`run-browser-test.sh`) runs after computational checks and before AI code review for `frontend`/`test` slices.

## 9. Harness-Generated Test Case Catalog

Test cases are organized by **requirement tag** (AC/FR/BR/NFR) derived from the backlog and docs:

| Artifact | Location |
|---|---|
| Doc resolution rules | `ai-harness/config/testgen-docs-map.json` |
| Generation state | `ai-harness/test-case-index.json` |
| Per-tag test cases | `ai-harness/test-cases/items/<tag>.json` |

The work queue is the union of all `acceptance` tags in `whole-app-backlog.json`. Docs are the authority (`docs/brds/`, `docs/technical/11-testing-plan.md`); harness rules map each tag to which doc files to read.

## 10. Defect Severity Model
- **P0**: capacity overflow, duplicate active registration, unauthorized critical update.
- **P1**: invalid attendance/eligibility outcomes, missing audit on sensitive actions.
- **P2**: incorrect user messaging or non-blocking policy mismatch.

## 11. Test Reporting Template
Each run should report:
- build metadata
- passed/failed by layer
- failed traceability tags (`BR-*`, `AC-*`)
- regression trend notes

## 12. BRD Traceability
- FR-01..FR-31
- BR-01..BR-22
- AC-01..AC-14
- NFR-02, NFR-10, NFR-13, NFR-15, NFR-16
