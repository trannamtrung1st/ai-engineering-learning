# We Event BRD - Business Rules

## 1. Rule Format
- Rule ID: `BR-xx`
- Each rule must be testable and traceable to related FR/AC.

## 2. Registration and Capacity Rules
- BR-01: Each participant can have at most 1 active registration per event at a given time.
- BR-02: Registration is valid only when the event is within its registration window.
- BR-03: Total registrations in `Registered` status must not exceed `EventCapacity`.
- BR-04: If event is full and waitlist is enabled, new registration is assigned `Waitlisted` by enqueue order.
- BR-04a: Waitlist position is assigned as `MAX(active positions) + 1` at enqueue time; positions are stable and not renumbered when other entries leave the queue.
- BR-04b: Active waitlist entry = `WaitlistEntry` where `promoted_at` and `expired_at` are both null.
- BR-05: If event is full and waitlist is disabled, new registration is rejected.
- BR-06: When a seat is available, the top waitlist participant is promoted first (FIFO), unless another configured priority rule applies (future scope).
- BR-06a: Promotion selects the active waitlisted registration with the lowest `position` value.
- BR-06b: Concurrent promotion attempts that detect queue order change return `WAITLIST_ORDER_CONFLICT` (retry-safe).

### 2.1 Registration and Waitlist Reason Codes (business-facing)

| Code | Meaning |
|------|---------|
| `REGISTRATION_REJECTED_FULL` | Event at capacity and waitlist is disabled |
| `WAITLIST_ORDER_CONFLICT` | Concurrent waitlist promotion; queue order changed — retry |
| `REGISTRATION_DUPLICATE_ACTIVE` | Participant already has an active registration for the event |
| `REGISTRATION_WINDOW_CLOSED` | Registration outside configured window |

## 3. Cancellation and Replacement Rules
- BR-07: Participant may cancel registration before `CancellationDeadline` (if configured for the event).
- BR-08: A valid cancellation by a seat holder (`Registered` or `CheckedIn`) must release one seat and trigger waitlist promotion in the same transaction.
- BR-08a: Waitlisted cancellation sets `WaitlistEntry.expired_at`; does not release a seat or promote another participant.
- BR-08b: Registered or `CheckedIn` cancellation frees one seat and runs FIFO promotion (BR-06a) atomically with the cancel write.
- BR-09: Cancellation after deadline may be blocked or require organizer approval (event policy dependent).

## 4. Check-in and Attendance Rules
- BR-10: Valid check-in can only be recorded from `CheckinOpenAt` to `CheckinCloseAt`.
- BR-11: Each registration can only have one valid check-in.
- BR-12: Registration with valid check-in is marked `Attended`; otherwise `Absent`.
- BR-13: Every check-in must include an audit trail (timestamp, actor, method).

## 5. Feedback Rules
- BR-14: If feedback is configured as mandatory (`feedbackRequired` true), participant must submit feedback within the configured feedback window to be certificate-eligible.
- BR-15: Feedback can only be submitted by the participant who holds a valid registration for the event, where registration state is `Attended`, event state is `Completed`, and current time is within `feedbackOpenAt..feedbackCloseAt`.
- BR-16: Each registration has at most one official feedback per event; duplicate submits are rejected unless in-window updates are allowed by event policy.

## 6. Certificate Eligibility Rules
- BR-17: Minimum condition for certificate eligibility is valid registration and `Attended` status. Eligibility evaluation is available only after attendance is finalized (`Attended`/`Absent` resolved).
- BR-18: If feedback is mandatory, participant must submit feedback within the configured feedback window (not merely before evaluation runs).
- BR-19: Eligibility result must be stored as `Eligible` or `NotEligible` with non-empty `reasonCode` and `reasonText`. Evaluation order is deterministic: attendance baseline is checked before mandatory-feedback requirement.
- BR-20: Post-finalization eligibility override transitions `Eligible → Revoked`; requires Organizer Admin permission, mandatory reason, immutable audit record, and visibility in organizer eligibility views. Organizer Staff and Participants cannot revoke.

### 6.1 Eligibility and Feedback Reason Codes (business-facing)

| Code | Meaning |
|------|---------|
| `NOT_ELIGIBLE_ATTENDANCE` | Did not attend / no valid check-in |
| `NOT_ELIGIBLE_FEEDBACK` | Mandatory feedback missing or not submitted within window |
| `FEEDBACK_REQUIRED` | Mandatory feedback not completed at evaluation time |
| `FEEDBACK_NOT_ALLOWED` | Feedback submit rejected (window, state, or authorization) |
| `FEEDBACK_DUPLICATE` | Second official submit when in-window updates are disallowed |
| `ELIGIBILITY_OVERRIDE_FORBIDDEN` | Revoke attempted without Organizer Admin role or reason |
| `ELIGIBILITY_REASON_MISSING` | Terminal eligibility persisted without reason payload |

## 7. Governance Rules
- BR-21: Only Organizer Admin can change event-level rule configurations.
- BR-22: Any major change to capacity/rules after registration opens must be logged with configuration version history.
