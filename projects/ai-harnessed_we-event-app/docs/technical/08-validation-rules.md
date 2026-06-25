# Validation Rules

## 1. Validation Strategy
Validation runs at three layers:
- API schema validation (shape/type/range).
- Authorization and scope validation.
- Domain business-rule validation (BR constraints).

All failures return deterministic error codes and user-safe messages.

## 2. Rule Catalog
| Rule ID | Validation Rule | Trigger | Outcome on Fail |
|---|---|---|---|
| BR-01 | One active registration per participant/event | registration request | `REGISTRATION_DUPLICATE_ACTIVE` |
| BR-02 | Registration only in registration window | registration request | `REGISTRATION_WINDOW_CLOSED` |
| BR-03 | `Registered` count never exceeds capacity | accept/promotion | `CAPACITY_EXCEEDED` |
| BR-04 | Full + waitlist enabled -> waitlist assign | registration request | route to waitlist |
| BR-05 | Full + waitlist disabled -> reject | registration request | `REGISTRATION_REJECTED_FULL` |
| BR-06 | Waitlist promotion FIFO | seat release | `WAITLIST_ORDER_CONFLICT` |
| BR-07 | Cancellation before deadline allowed | cancellation request | `CANCELLATION_DEADLINE_PASSED` |
| BR-08 | Valid cancellation frees seat + triggers promotion | cancellation success | internal invariant error if not satisfied |
| BR-09 | Late cancellation policy enforced | cancellation request | `CANCELLATION_NOT_ALLOWED` |
| BR-10 | Check-in only in check-in window | check-in request | `CHECKIN_WINDOW_CLOSED` |
| BR-11 | One valid check-in per registration | check-in request | `CHECKIN_ALREADY_RECORDED` |
| BR-12 | Attendance inferred from check-in | event completion | reconciliation error |
| BR-13 | Check-in must include audit metadata | check-in write | `AUDIT_METADATA_MISSING` |
| BR-14 | Mandatory feedback required for eligibility | evaluation | `FEEDBACK_REQUIRED` |
| BR-15 | Feedback only by valid registration holder | feedback submit | `FEEDBACK_NOT_ALLOWED` |
| BR-16 | One official feedback per event | feedback submit | `FEEDBACK_DUPLICATE` |
| BR-17 | Baseline eligibility requires valid registration + attended | evaluation | `NOT_ELIGIBLE_ATTENDANCE` |
| BR-18 | Mandatory feedback completion enforced | evaluation | `NOT_ELIGIBLE_FEEDBACK` |
| BR-19 | Eligibility stored with reason | evaluation persist | `ELIGIBILITY_REASON_MISSING` |
| BR-20 | Eligibility override requires admin + reason | revoke/override | `ELIGIBILITY_OVERRIDE_FORBIDDEN` |
| BR-21 | Only admin can modify event-level rules | config update | `EVENT_RULE_CHANGE_FORBIDDEN` |
| BR-22 | Post-open critical changes are audit-logged | config update | `AUDIT_REQUIRED_FOR_CRITICAL_CHANGE` |

## 3. Validation Pipeline by Operation
### Registration request
1. auth + actor scope
2. event state and registration window
3. dedup active registration
4. capacity decision
5. assign state and persist transactionally

### Check-in request
1. auth + check-in capability
2. event check-in window
3. existing valid check-in check
4. persist check-in + state transition
5. write audit metadata

### Eligibility evaluation
1. confirm registration and attendance status
2. validate feedback requirement
3. compute result and reason
4. persist result in one atomic write

## 4. Input Validation Baselines
- UUID format for identifiers.
- ISO-8601 timestamps for all windows.
- bounded text fields for free-form reasons/comments.
- enum validation for all state/action fields.

## 5. Determinism Requirements
- Rule evaluation order is fixed and documented.
- Same inputs always produce the same output state and reason.
- Override paths are explicit and audited.

## 6. BRD Traceability
- BR-01..BR-22 (primary)
- FR-06..FR-21, FR-25..FR-27
- AC-01..AC-12
