# We Event BRD - Functional Requirements

## 1. Requirement Format
- Requirement ID: `FR-xx`
- Actor type: Organizer Admin, Organizer Staff, Participant, System
- Objective: describe the business value to be delivered

Detailed requirements in Section 5 use this structure per item:
- **Actor** — who performs or receives the capability
- **Preconditions** — state and scope gates that must hold
- **Behavior** — what the system does on success
- **Rejections** — deterministic failure outcomes (error codes where applicable)
- **Traces** — related `BR-xx` and `AC-xx` identifiers

API contracts for registration/waitlist are in [`docs/technical/05-api-design.md`](../technical/05-api-design.md) §2.2; feedback/eligibility in §2.4; pagination in §3. Waitlist UI patterns in [`docs/ui-ux/11-wireframes.md`](../ui-ux/11-wireframes.md) (organizer waitlist wireframe).

## 2. Event Management
- FR-01: Organizer Admin can create an event with basic information (name, description, time, location, organizing unit).
- FR-02: Organizer Admin can configure maximum event capacity.
- FR-03: Organizer Admin can configure registration open/close timing.
- FR-04: Organizer Admin can publish/pause an event.

## 3. Registration and Capacity

- FR-05: Participant can view events currently open for registration.
- FR-06: Participant can register at most once per event (duplicate prevention).
- FR-07: System automatically assigns `Registered` if seats are available.

### 3.1 Organizer — Waitlist Policy Configuration

**FR-02a** — Configure waitlist policy
- **Actor**: Organizer Admin
- **Preconditions**: Event exists; actor has organization/event scope
- **Behavior**:
  - Set `waitlistEnabled` on `EventRuleConfig` alongside capacity.
  - Edit freely on Draft events before registration opens.
  - After registration opens, changes follow BR-22 (audit, reason, configuration version).
  - When enabled, full events queue new registrations instead of rejecting them (BR-04).
- **Rejections**: `EVENT_RULE_CHANGE_FORBIDDEN` (Organizer Staff or Participant); `AUDIT_REQUIRED_FOR_CRITICAL_CHANGE` (post-open change without reason)
- **Traces**: BR-04, BR-05, BR-21, BR-22, AC-02

### 3.2 System — Registration Outcome Assignment

**FR-08** — Assign waitlisted status when full
- **Actor**: System (on registration request)
- **Preconditions**: Event within registration window; no duplicate active registration (BR-01, BR-02); seat count at capacity (BR-03); `waitlistEnabled` is true
- **Behavior**:
  - Assign registration state `Waitlisted`.
  - Create active `WaitlistEntry` with monotonic `position` (BR-04a).
  - Return `waitlistPosition` in registration response.
  - Write registration audit and status history.
- **Rejections**: N/A (success path); upstream failures use BR-01/BR-02 codes
- **Traces**: BR-04, BR-04a, BR-04b, AC-02a

**FR-09** — Reject registration when full and waitlist disabled
- **Actor**: System (on registration request)
- **Preconditions**: Event within registration window; no duplicate active registration; seat count at capacity; `waitlistEnabled` is false
- **Behavior**: Reject registration request without creating a registration row in an active state.
- **Rejections**: `REGISTRATION_REJECTED_FULL` with user-safe message
- **Traces**: BR-05, AC-02b

### 3.3 Participant — Status Tracking and Cancellation

**FR-10** — Track registration status in near real-time
- **Actor**: Participant
- **Preconditions**: Authenticated; holds or held a registration for the event
- **Behavior**: Event detail and My Registrations reflect current registration state, reason text, and latest `updatedAt` after register, cancel, or promotion.
- **Rejections**: `401` unauthenticated; `403`/`404` for another participant's registration
- **Traces**: AC-01, AC-02

**FR-10a** — View waitlist queue position
- **Actor**: Participant (own registration only)
- **Preconditions**: Registration state is `Waitlisted`; active `WaitlistEntry` exists (BR-04b)
- **Behavior**:
  - Expose `waitlistPosition` on event detail and My Registrations.
  - UI copy explains queue position is assigned at enrollment time and that promotion occurs when a seat opens (FIFO).
  - Position updates when participant is promoted to `Registered` (`waitlistPosition` becomes null).
- **Rejections**: N/A on read; position omitted when not waitlisted
- **Traces**: BR-04a, AC-02e

**FR-11** — Cancel registration under allowed conditions
- **Actor**: Participant (own registration) or Organizer Admin (organizer cancel)
- **Preconditions**: Registration in cancellable state; within cancellation policy (BR-07, BR-09)
- **Behavior**: Transition to `CancelledByUser` or `CancelledByOrganizer`; write audit and status history; return updated registration payload.
- **Rejections**: `CANCELLATION_DEADLINE_PASSED`, `CANCELLATION_NOT_ALLOWED`
- **Traces**: BR-07, BR-08, BR-09, AC-02c, AC-02d

**FR-11a** — Cancel while waitlisted
- **Actor**: Participant (own registration) or Organizer Admin
- **Preconditions**: Registration state is `Waitlisted`; cancellation policy satisfied (BR-07)
- **Behavior**:
  - Transition to cancelled state.
  - Mark active `WaitlistEntry` as expired (`expired_at`); do **not** release a seat or promote another participant (BR-08a).
- **Rejections**: Same as FR-11
- **Traces**: BR-08a, AC-02d

### 3.4 System — Waitlist Promotion

**FR-12** — Promote from waitlist when a seat becomes available
- **Actor**: System (triggered by seat-holding cancellation or capacity increase)
- **Preconditions**: At least one active waitlist entry exists; a seat is available (BR-03)
- **Behavior**:
  - Select the active entry with lowest `position` (BR-06a).
  - Atomically transition that registration `Waitlisted → Registered` in the same transaction as the seat release.
  - Mark `WaitlistEntry.promoted_at`; clear participant-visible `waitlistPosition`.
  - Promote exactly one registration per freed seat.
  - Write audit (`registration.promoted_from_waitlist`) and status history.
  - Cancel response may include optional `promoted` registration when promotion ran (BR-08b).
- **Rejections**: `WAITLIST_ORDER_CONFLICT` when concurrent promotion detects queue order change (BR-06b); caller may retry
- **Traces**: BR-06, BR-06a, BR-06b, BR-08b, AC-02c, AC-02g

### 3.5 Organizer — Waitlist Operations

**FR-30a** — View and monitor waitlist queue
- **Actor**: Organizer Admin and scoped Organizer Staff
- **Preconditions**: Actor authorized for event scope
- **Behavior**:
  - Paginated waitlist via `GET /events/{eventId}/waitlist`; default sort `position:asc` (FIFO preserved across pages).
  - Each row: queue position, participant identity, registration state, enqueued timestamp.
  - Operations dashboard waitlist KPI links to this view.
  - Registrations list may also show `Waitlisted` rows with position for cross-filtering; dedicated waitlist view is the FIFO queue source of truth.
- **Rejections**: `401` unauthenticated; `403` out-of-scope
- **Traces**: FR-30, FR-31, AC-02f, AC-13, AC-14

## 4. Check-in and Attendance
- FR-13: Organizer Staff can check in participants.
- FR-14: Participant can self check-in when self-service check-in is enabled.
- FR-15: System only records valid check-ins within the configured check-in window.
- FR-16: System stores check-in history (timestamp, check-in source, operator).
- FR-17: System updates attendance status (`Attended`/`Absent`) after event completion.

## 5. Feedback and Certificate

### 5.1 Organizer — Feedback Module Configuration

**FR-18** — Configure feedback policy and window
- **Actor**: Organizer Admin
- **Preconditions**: Event exists; actor has organization/event scope
- **Behavior**:
  - Set `feedbackRequired` (mandatory vs optional) on `EventRuleConfig`.
  - Set feedback window (`feedbackOpenAt`, `feedbackCloseAt`) with `feedbackOpenAt < feedbackCloseAt`.
  - Edit policy freely on Draft events before registration opens.
  - After registration opens, critical feedback-policy changes require Organizer Admin actor, mandatory reason, immutable audit record, and configuration version increment (BR-22).
  - Event operations dashboard reflects configured feedback policy; when feedback is mandatory, organizers can see mandatory-feedback outstanding count (ties to FR-22).
- **Rejections**: `EVENT_RULE_CHANGE_FORBIDDEN` (Organizer Staff or Participant); `AUDIT_REQUIRED_FOR_CRITICAL_CHANGE` (post-open change without reason); invalid window (`feedbackOpenAt >= feedbackCloseAt`)
- **Traces**: BR-14, BR-21, BR-22, AC-08, AC-09

### 5.2 Participant — Feedback Submission

**FR-19** — Submit post-event feedback
- **Actor**: Participant (own registration only)
- **Preconditions**:
  - Event state is `Completed`
  - Registration state is `Attended`
  - Current time is within `[feedbackOpenAt, feedbackCloseAt]`
  - Actor holds valid registration for the event (`registrationId` matches actor)
- **Behavior**:
  - Submit one official feedback payload with non-empty `answers`.
  - Optional in-window update of answers when event policy allows (BR-16).
  - Persist feedback linked 0..1 to registration; emit `FeedbackSubmitted`.
  - Return immediate success payload (`feedbackId`, `submittedAt`).
- **Rejections**: `FEEDBACK_NOT_ALLOWED` (window, event state, registration state, or authz); `FEEDBACK_DUPLICATE` (second official submit when updates disallowed); `401` unauthenticated; `403` cross-participant or organizer submit
- **Traces**: BR-15, BR-16, AC-08

| Gate | Rule |
|------|------|
| Event state | `Completed` |
| Registration state | `Attended` |
| Actor | Participant, own `registrationId` only |
| Time | Within feedback window |
| Uniqueness | One official feedback per registration; in-window updates per BR-16 |
| Payload | Non-empty `answers` object |

### 5.3 System — Eligibility Evaluation

**FR-20** — Evaluate certificate eligibility
- **Actor**: System (triggered on participant eligibility read or organizer list access)
- **Preconditions**: Attendance finalized (`Attended` or `Absent` resolved per FR-17)
- **Behavior** — deterministic evaluation order:
  1. Attendance baseline: valid registration and `Attended` → else `NotEligible` with `NOT_ELIGIBLE_ATTENDANCE`
  2. Mandatory feedback: when `feedbackRequired` is true, feedback must be submitted within configured window → else `NotEligible` with `NOT_ELIGIBLE_FEEDBACK`
  3. Persist terminal result `Eligible` or `NotEligible` with `reasonCode`, `reasonText`, and `evaluatedAt` (BR-19)
  4. Initial state `PendingEvaluation`; re-evaluate when inputs change (e.g. feedback submitted after initial `NotEligible`)
- **Rejections**: Evaluation unavailable before attendance finalization (`404` / not found on participant read)
- **Traces**: BR-14, BR-17, BR-18, BR-19, AC-09

### 5.4 Participant — Eligibility Result View

**FR-20a** — View own certificate eligibility result
- **Actor**: Participant
- **Preconditions**: Own registration for the event; attendance finalized
- **Behavior**: Return system-evaluated eligibility result (`Eligible`, `NotEligible`, or `PendingEvaluation` before first evaluation) with non-empty `reasonCode` and `reasonText` for terminal outcomes; result updates when system re-evaluates after input changes
- **Rejections**: `401` unauthenticated; `403`/`404` when accessing another participant's eligibility or before attendance finalization
- **Traces**: BR-19, AC-09

### 5.5 Organizer — Eligibility List Operations

**FR-21** — View participant eligibility lists
- **Actor**: Organizer Admin and scoped Organizer Staff
- **Preconditions**: Event in post-attendance phase; actor authorized for event scope
- **Behavior**:
  - View paginated eligibility list including `Eligible`, `NotEligible`, and `Revoked` rows.
  - Each row exposes participant identity, `registrationId`, terminal result, and non-empty `reasonCode` / `reasonText`.
  - Filter by eligibility status (`eligibility` query param); default sort `participantId:asc`; paginated envelope per FR-30/FR-31.
  - First list access may trigger evaluation and persistence for registrations not yet evaluated.
- **Rejections**: `401` unauthenticated; `403` out-of-scope (Participant, Staff outside assignment, Admin outside organization)
- **Traces**: BR-19, BR-20, AC-10, AC-13, AC-14

### 5.6 Organizer Admin — Eligibility Revocation

**FR-37** — Revoke eligible certificate status
- **Actor**: Organizer Admin only
- **Preconditions**: Registration has terminal `Eligible` result; actor has organization/event scope
- **Behavior**: Transition `Eligible → Revoked` with mandatory `reasonCode` and `reasonText`; write immutable audit record; revoked row visible in organizer eligibility list with override reason
- **Rejections**: `ELIGIBILITY_OVERRIDE_FORBIDDEN` (Organizer Staff, Participant, or missing reason)
- **Traces**: BR-20, AC-10, AC-11

## 6. Monitoring and Reporting
- FR-22: Organizer Admin can view event overview (registrations, waitlist, check-ins, feedback completion, configured feedback policy, eligibility summary).
- FR-23: Organizer Admin can retrieve registration status change history.
- FR-24: Organizer Admin can export event operational data for internal reporting.

## 7. Access and Roles
- FR-25: System enforces role-based access (Admin, Staff, Participant).
- FR-26: Participant can only operate on their own registration data.
- FR-27: Staff can only operate within assigned event scope.

## 8. List Browsing and Pagination

Listing UX contracts: [`docs/ui-ux/14-listing-pages-search-filter-sort.md`](../ui-ux/14-listing-pages-search-filter-sort.md). API pagination: [`docs/technical/05-api-design.md`](../technical/05-api-design.md) §3.

**FR-28** — Browse paginated event listings (participant discovery)
- **Actor**: Participant
- **Preconditions**: Authenticated
- **Behavior**:
  - Paginated card grid via `GET /events` with `q` (name/location/description), optional `state` filter, and `sort` (`startAt:asc` default, `updatedAt:desc`).
  - FilterBar with debounced search, state filter, and sort select; changing criteria resets to page 1.
  - Cards show registration status overlay when participant has an active registration.
- **Rejections**: `400` invalid pagination/sort/state; `401` unauthenticated
- **Traces**: AC-13, AC-14, AC-18a, AC-18b, AC-18d

**FR-29** — View paginated my registrations
- **Actor**: Participant
- **Preconditions**: Authenticated
- **Behavior**:
  - Paginated list via `GET /me/registrations` with optional `state` filter and `sort` (`updatedAt:desc` default).
  - Rows show event name, registration state, reason text, `waitlistPosition` when `Waitlisted`, and rule-gated quick actions.
  - Status filter and sort select in FilterBar; page reset on criteria change.
- **Rejections**: `400` invalid filter/sort; `401` unauthenticated
- **Traces**: FR-10a, AC-13, AC-14, AC-18c

**FR-30** — View paginated organizer operational lists
- **Actor**: Organizer Admin and scoped Organizer Staff
- **Preconditions**: Actor authorized for event scope
- **Behavior**:
  - Per-endpoint filters and sorts per listing matrix (registrations, waitlist, attendance, eligibility, audit).
  - Organizer events list: search + state filter + sort (includes `Draft`).
  - Registrations list: state filter; waitlist position column for `Waitlisted` rows.
  - Waitlist list: FIFO `position:asc` only; dedicated queue view (FR-30a).
  - Eligibility: segmented filter by `eligibility` status.
  - All lists use paginated envelope (FR-31).
- **Rejections**: `401` unauthenticated; `403` out-of-scope; `400` invalid query params
- **Traces**: FR-30a, AC-13, AC-14, AC-18e

- FR-31: System returns total result count with each paginated list response.

## 9. Identity and Session
- FR-32: Participant can register a user account with email and password.
- FR-33: User can sign in with email and password and receive an authenticated JWT session.
- FR-34: User can sign out, clearing the client session.

## 10. Event Media
- FR-35: Organizer Admin can upload or replace an event cover image during create/edit.
- FR-36: Participants and organizers see event cover images on discovery cards and event detail.
