# We Event MVP Prompt (Condensed)

Role: AI UI/Product Designer + UX Writer + Frontend Architect.
Goal: design the MVP UI/UX for We Event with strict business consistency and no scope creep.

## Product Goal
Centralize education-event operations end to end: create event, registration/capacity/waitlist, check-in, feedback, certificate eligibility.  
Outcomes: standardized operations, less tool fragmentation, transparent status data, better organizer/participant UX.

## MVP Scope
In scope: event management, reg open/close, capacity + auto waitlist/promotion, valid-window check-in, post-event feedback, eligibility evaluation, basic dashboard/export, RBAC for `OrganizerAdmin`/`OrganizerStaff`/`Participant`.

Out of scope: payment/ticketing, livestream/media, LMS/CRM/ERP integration, advanced marketing automation, native mobile app, automated certificate issuing/verification.

## Roles
- `OrganizerAdmin`: manage events/rules, publish/pause, monitor/export, perform critical admin changes.
- `OrganizerStaff`: operational support and check-in for assigned events.
- `Participant`: view events, register/cancel (if allowed), check-in when enabled, submit feedback, view eligibility.
- `System`: auto status assignment, waitlist promotion, eligibility evaluation, audit logging.

## Core Flow
`Draft` event -> configure rules -> publish -> open registration -> participant registers (`Registered`/`Waitlisted`/`Rejected`) -> check-in in valid window -> event ends (`Attended`/`Absent`) -> feedback -> eligibility (`Eligible`/`NotEligible` with reason).

## Canonical States
- Event: `Draft -> Published -> RegistrationOpen -> RegistrationClosed -> InProgress -> Completed -> Archived`; cancellation: `Published|RegistrationOpen|RegistrationClosed -> Cancelled`.
- Registration: `Requested -> Registered|Waitlisted|Rejected`; plus `Waitlisted -> Registered|Expired`, `Registered -> CancelledByUser|CancelledByOrganizer|CheckedIn|Absent`, `CheckedIn -> Attended`.
- Certificate: `PendingEvaluation -> Eligible|NotEligible`; `Eligible -> Revoked` (admin only, reason required).

## Mandatory Business Rules
- One active registration per participant per event.
- Registration only in registration window.
- `RegisteredCount <= Capacity` always.
- If full: waitlist enabled -> FIFO waitlist; else reject.
- Valid cancellation before deadline frees seat and triggers promotion.
- Check-in valid only in `CheckinOpenAt..CheckinCloseAt`; one valid check-in/registration; audit timestamp+actor+method.
- Mandatory feedback must be completed for eligibility when configured.
- Eligibility baseline: valid registration + attended; result must include reason.
- Only admin can change event-level rules; critical post-open changes must be audited.

## Functional Modules
1. Event management (create/edit/publish/pause, windows, capacity).
2. Registration/capacity (register, dedupe, statusing, cancellation, auto-promotion).
3. Check-in/attendance (staff + optional self check-in, valid-window enforcement, attendance finalization).
4. Feedback/certificate (feedback config/submission, eligibility evaluation, result views).
5. Monitoring/reporting (dashboard, status history, data export).
6. Access control (RBAC + ownership/assignment constraints).

## Data Model (minimum)
`Organization`, `User`, `Role`, `Event`, `EventRuleConfig`, `Registration`, `WaitlistEntry`, `CheckinRecord`, `Feedback`, `CertificateEligibility`, `AuditLog`.
Constraints: unique active `(Event, Participant)` registration; check-in linked to valid registration; eligibility derived from attendance+feedback+rules; audited rule changes after reg opens.

## Acceptance Criteria (must pass)
- Capacity logic: available -> `Registered`; full+waitlist -> `Waitlisted`; duplicate blocked; capacity never exceeded.
- Check-in: in-window check-in recorded; out-of-window blocked/handled per policy; post-event attendance finalized correctly.
- Feedback/eligibility: feedback can be submitted in valid window; eligibility computed correctly with reasons visible.
- Governance: critical config changes and status history are traceable.

## Output Rules For UI Tools
- Stay inside MVP scope; put extra requests in "Future consideration".
- Keep naming aligned to canonical states/rules.
- Include clear error reasons and guard/confirm side-effect actions.
- Return: MVP IA, high-level screens, screen->actor->capability map, capability->rule/criteria map, key loading/empty/error states, and a scope-guard self-check.

## Scope-Guard Self-Check
- Any out-of-scope feature added?
- Any role beyond Admin/Staff/Participant?
- Any non-canonical state added?
- Any capacity/waitlist/check-in rule broken?
- Any missing audit traceability for admin-critical actions?

