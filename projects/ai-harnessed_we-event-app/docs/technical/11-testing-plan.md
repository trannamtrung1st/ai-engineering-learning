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
Minimum pre-merge gates:
- all unit tests pass
- all integration tests pass
- scenario matrix acceptance suite passes
- no unresolved canonical-state naming drift
- no missing audit event for critical operations

## 9. Defect Severity Model
- **P0**: capacity overflow, duplicate active registration, unauthorized critical update.
- **P1**: invalid attendance/eligibility outcomes, missing audit on sensitive actions.
- **P2**: incorrect user messaging or non-blocking policy mismatch.

## 10. Test Reporting Template
Each run should report:
- build metadata
- passed/failed by layer
- failed traceability tags (`BR-*`, `AC-*`)
- regression trend notes

## 11. BRD Traceability
- FR-01..FR-27
- BR-01..BR-22
- AC-01..AC-12
- NFR-02, NFR-10, NFR-13, NFR-15
