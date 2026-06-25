# We Event BRD - Acceptance Criteria and MVP/Future Scope

## 1. Acceptance criteria

## 1.1 Registration and Capacity
- AC-01: When seats are available, participant registration succeeds with `Registered` status.
- AC-02: When event is full and waitlist is enabled, participant receives `Waitlisted` status.
- AC-03: System blocks duplicate registration for the same participant and event.
- AC-04: Total `Registered` participants never exceeds configured capacity.

## 1.2 Check-in and Attendance
- AC-05: Check-in within valid window is recorded with timestamp.
- AC-06: Out-of-window check-in is rejected or handled per configured rule.
- AC-07: After event completion, participant with valid check-in is marked `Attended`.

## 1.3 Feedback and Certificate
- AC-08: Participant can submit feedback within feedback window.
- AC-09: System evaluates eligibility by rules and returns `Eligible`/`NotEligible`.
- AC-10: Organizer can view certificate-eligible participant list with reasons.

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

## 2. MVP scope
- Event CRUD with publish/pause.
- Event registration with capacity control.
- Automatic waitlist and promotion when seats open up.
- Check-in with valid time-window controls.
- Post-event feedback.
- Certificate eligibility evaluation based on attendance + feedback rules.
- Basic operations dashboard and event data export.
- Paginated list browsing for participant discovery and organizer operations.
- Credential-based user authentication (signup, login, logout).
- Event cover image upload and display.

## 3. Future scope
- Advanced waitlist priority policies (priority groups, scoring).
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
- Registration/capacity: FR-05 to FR-12, BR-01 to BR-09, AC-01 to AC-04.
- Check-in/attendance: FR-13 to FR-17, BR-10 to BR-13, AC-05 to AC-07.
- Feedback/certificate: FR-18 to FR-21, BR-14 to BR-20, AC-08 to AC-10.
- Governance/traceability: FR-22 to FR-27, BR-21 to BR-22, AC-11 to AC-12.
- List pagination: FR-28 to FR-31, NFR-16, AC-13 to AC-14.
- Identity/session: FR-32 to FR-34, NFR-07, NFR-08, NFR-17, AC-15 to AC-16.
- Event media: FR-35 to FR-36, NFR-18, AC-17.
