# We Event BRD - Business Rules

## 1. Rule Format
- Rule ID: `BR-xx`
- Each rule must be testable and traceable to related FR/AC.

## 2. Registration and Capacity Rules
- BR-01: Each participant can have at most 1 active registration per event at a given time.
- BR-02: Registration is valid only when the event is within its registration window.
- BR-03: Total registrations in `Registered` status must not exceed `EventCapacity`.
- BR-04: If event is full and waitlist is enabled, new registration is assigned `Waitlisted` by timestamp order.
- BR-05: If event is full and waitlist is disabled, new registration is rejected.
- BR-06: When a seat is available, the top waitlist participant is promoted first (FIFO), unless another configured priority rule applies.

## 3. Cancellation and Replacement Rules
- BR-07: Participant may cancel registration before `CancellationDeadline` (if configured for the event).
- BR-08: A valid cancellation must release one seat and trigger waitlist promotion flow.
- BR-09: Cancellation after deadline may be blocked or require organizer approval (event policy dependent).

## 4. Check-in and Attendance Rules
- BR-10: Valid check-in can only be recorded from `CheckinOpenAt` to `CheckinCloseAt`.
- BR-11: Each registration can only have one valid check-in.
- BR-12: Registration with valid check-in is marked `Attended`; otherwise `Absent`.
- BR-13: Every check-in must include an audit trail (timestamp, actor, method).

## 5. Feedback Rules
- BR-14: If feedback is configured as mandatory, participant must submit feedback to be certificate-eligible.
- BR-15: Feedback can only be submitted by a participant with valid registration for the event.
- BR-16: Each participant submits one official feedback per event (updates can be allowed within window if configured).

## 6. Certificate Eligibility Rules
- BR-17: Minimum condition for certificate eligibility is valid registration and `Attended` status.
- BR-18: If feedback is mandatory, participant must complete feedback within the configured window.
- BR-19: Eligibility result must be stored as `Eligible` or `NotEligible` with reason.
- BR-20: Any post-finalization eligibility change requires Organizer Admin permission and a mandatory reason.

## 7. Governance Rules
- BR-21: Only Organizer Admin can change event-level rule configurations.
- BR-22: Any major change to capacity/rules after registration opens must be logged with configuration version history.
