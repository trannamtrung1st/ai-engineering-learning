# We Event BRD - Acceptance Criteria and MVP/Future Scope

## 1. Acceptance criteria

## 1.1 Registration and Capacity
- AC-01: When seats are available, participant registration succeeds with `Registered` status.
- AC-02: When event is full and waitlist is enabled, participant receives `Waitlisted` status (see AC-02a–g for waitlist detail).
- AC-03: System blocks duplicate registration for the same participant and event.
- AC-04: Total `Registered` participants never exceeds configured capacity.

### Waitlist (AC-02)
- AC-02a: Full event + `waitlistEnabled` true → registration state `Waitlisted` with `waitlistPosition >= 1`.
- AC-02b: Full event + `waitlistEnabled` false → reject with `REGISTRATION_REJECTED_FULL`.
- AC-02c: Registered participant cancel within policy promotes FIFO next waitlisted participant to `Registered`.
- AC-02d: Waitlisted participant cancel expires queue entry; no promotion of other participants.
- AC-02e: Participant sees `waitlistPosition` on event detail and My Registrations when `Waitlisted`.
- AC-02f: Organizer waitlist list returns FIFO order (`position:asc`) preserved across paginated pages.
- AC-02g: Concurrent promotion either succeeds or returns `WAITLIST_ORDER_CONFLICT` without corrupting queue order.

## 1.2 Check-in and Attendance
- AC-05: Check-in within valid window is recorded with timestamp.
- AC-06: Out-of-window check-in is rejected or handled per configured rule.
- AC-07: After event completion, participant with valid check-in is marked `Attended`.

## 1.3 Feedback and Certificate

### Participant feedback (AC-08)
- AC-08a: Attended participant submits feedback on a `Completed` event within the feedback window; submission succeeds with `feedbackId` and `submittedAt`.
- AC-08b: Feedback submission before `feedbackOpenAt` or after `feedbackCloseAt` is rejected with `FEEDBACK_NOT_ALLOWED`.
- AC-08c: Non-`Attended` registration (e.g. `Registered`, `Absent`) cannot submit feedback.
- AC-08d: Duplicate official submission is rejected with `FEEDBACK_DUPLICATE` when in-window updates are not allowed.
- AC-08e: In-window feedback update succeeds when event policy allows (BR-16).
- AC-08f: Unauthenticated submit returns `401`; cross-participant or organizer submit returns `403`.
- AC-08g: Empty `answers` payload is rejected at validation boundary.

### Eligibility evaluation and participant view (AC-09)
- AC-09a: System evaluates eligibility and returns terminal `Eligible` or `NotEligible` with non-empty reason fields.
- AC-09b: Attended participant with optional feedback (`feedbackRequired` false) evaluates to `Eligible` when attendance baseline passes.
- AC-09c: Attended participant with mandatory feedback missing evaluates to `NotEligible` with `NOT_ELIGIBLE_FEEDBACK`.
- AC-09d: `Absent` registration evaluates to `NotEligible` with `NOT_ELIGIBLE_ATTENDANCE`.
- AC-09e: Participant views own eligibility result with reason after attendance finalization (FR-20a).
- AC-09f: Eligibility is unavailable before attendance finalization.
- AC-09g: System re-evaluates and updates stored result when feedback is submitted after an initial `NotEligible` outcome.

### Organizer eligibility views (AC-10)
- AC-10a: Organizer Admin and scoped Organizer Staff view paginated eligibility lists with `Eligible` and `NotEligible` rows, each with reason fields.
- AC-10b: Organizer filters eligibility list by status (`Eligible`, `NotEligible`); invalid filter returns `400`.
- AC-10c: Eligibility list returns correct pagination metadata (`items`, `total`, `totalPages`); page beyond last returns empty `items` (AC-13 pattern).
- AC-10d: `Revoked` eligibility appears in organizer list with override reason (BR-20, FR-37).
- AC-10e: Unauthenticated list access returns `401`; Participant and out-of-scope Staff return `403`.
- AC-10f: Organizer eligibility UI uses segmented views and does not load unbounded datasets client-side (AC-14).

## 1.4 Governance and Traceability
- AC-11: All critical event configuration changes are audit logged.
- AC-12: Organizer can trace registration status change history.

## 1.5 List Pagination
- AC-13: Paginated list request with `page`/`pageSize` returns correct `items`, `total`, and `totalPages`; a page beyond the last page returns empty `items` with valid metadata.
- AC-14: Listing pages expose prev/next (or equivalent page control) and do not render full unbounded datasets client-side.

## 1.6 Identity and Session
- AC-15: Unauthenticated access to protected API endpoints or routes returns 401 or redirects to login.
- AC-16: Signup → login → view own registrations succeeds end-to-end.

## 1.7 Event Media
- AC-17: Organizer uploads a cover image; participant sees it on event list and event detail.

## 1.8 Listing search, filter, and sort (AC-18)

- AC-18a: Participant event discovery: `q` and `state` filter return matching paginated results; changing filter or search resets to page 1.
- AC-18b: Invalid `sort` on any list endpoint returns `400 INVALID_INPUT`.
- AC-18c: My registrations `state` filter is applied server-side (`GET /me/registrations?state=...`).
- AC-18d: Participant event discovery sort control updates API `sort` query param (e.g. `startAt:asc`, `updatedAt:desc`).
- AC-18e: Organizer registrations list filtered by `state=Waitlisted` includes `waitlistPosition` on each row.

## 2. MVP scope
- Event CRUD with publish/pause.
- Event registration with capacity control.
- Automatic waitlist and promotion when seats open up.
- Check-in with valid time-window controls.
- Post-event feedback.
- Certificate eligibility evaluation based on attendance + feedback rules.
- Basic operations dashboard and event data export.
- Paginated list browsing for participant discovery and organizer operations (search, filter, sort per [`docs/ui-ux/14-listing-pages-search-filter-sort.md`](../ui-ux/14-listing-pages-search-filter-sort.md)).
- Credential-based user authentication (signup, login, logout).
- Event cover image upload and display.

## 3. Future scope
- Advanced waitlist priority policies (priority groups, scoring).
- Participant identity search on organizer operational tables (registrations, waitlist, attendance).
- Multi-channel notification integration (email, push, chat apps).
- Training/internal system integration to sync participation outcomes.
- Digitalized certificate issuance process (auto issue, verify link, QR verification).
- Advanced analytics on event quality by topic/attendance/feedback sentiment.
- Native mobile app support and advanced offline check-in mode.

## 4. MVP exit indicators
- At least one organizing unit runs events end-to-end in We Event without fragmented tools.
- Full event lifecycle is managed in one system from registration to certificate evaluation.
- Event operational data is reliable enough to support improvement decisions for subsequent runs.

## 5. Documentation Coverage Check
- Registration/capacity: FR-05 to FR-12, FR-02a, FR-10a, FR-11a, FR-30a, BR-01 to BR-09, BR-04a–b, BR-06a–b, BR-08a–b, AC-01 to AC-04, AC-02a–g.
- Check-in/attendance: FR-13 to FR-17, BR-10 to BR-13, AC-05 to AC-07.
- Feedback/certificate: FR-18 to FR-21, FR-20a, FR-37, BR-14 to BR-20, AC-08 to AC-10.
- Governance/traceability: FR-22 to FR-27, BR-21 to BR-22, AC-11 to AC-12.
- List pagination and listing UX: FR-28 to FR-31, NFR-05, NFR-16, AC-13, AC-14, AC-18a–e; UI [`docs/ui-ux/14-listing-pages-search-filter-sort.md`](../ui-ux/14-listing-pages-search-filter-sort.md).
- Identity/session: FR-32 to FR-34, NFR-07, NFR-08, NFR-17, AC-15 to AC-16.
- Event media: FR-35 to FR-36, NFR-18, AC-17.
