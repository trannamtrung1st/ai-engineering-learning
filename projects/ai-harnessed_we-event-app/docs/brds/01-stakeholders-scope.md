# We Event BRD - Stakeholders and Scope

## 1. Stakeholders and Actors

## 1.1 Primary Stakeholders
- Educational organizations/clubs/event-owning units: need a centralized event management tool.
- Participants (students/learners): need a clear registration and participation process.
- Student affairs/training management units: need transparent data for reporting and participation confirmation.

## 1.2 System Actors
- Organizer Admin:
  - Create/edit/publish events.
  - Configure capacity, waitlist, check-in, feedback policy (`feedbackRequired`, feedback window), and certificate eligibility rules.
  - Monitor event operations dashboard (including feedback completion and eligibility summary).
  - View paginated eligibility lists (`Eligible`, `NotEligible`, `Revoked`) with reasons; revoke `Eligible` status with mandatory reason and audit.
- Organizer Staff:
  - Support check-in operations at events.
  - View paginated eligibility lists for assigned events (read-only; no policy changes or revocations).
  - Handle operational tasks within granted permissions.
- Participant:
  - View events, register, cancel registration (if allowed), check in, submit feedback (own `Attended` registration, within feedback window).
  - View own certificate eligibility result and reason after attendance finalization.
- System:
  - Automatically update registration/waitlist statuses.
  - Automatically enforce business rules and record history.
  - Evaluate certificate eligibility deterministically and persist results with reasons.

## 2. Scope

## 2.1 In Scope (MVP)
- Event information management and registration open/close scheduling.
- Capacity-controlled event registration.
- Automatic waitlist when full.
- Event check-in.
- Post-event feedback collection with configurable mandatory/optional policy and feedback window.
- Certificate eligibility evaluation based on attendance and feedback rules, with reason-backed outcomes for participants and organizers.
- Registration status management per participant.
- Paginated list browsing for participant event discovery and organizer operational views.
- User account registration and credential-based sign-in/sign-out.
- Event cover image upload and display (single image per event).

## 2.2 Out of Scope (MVP)
- Online payment/ticketing.
- Livestream and full media content management (galleries, video hosting, CDN workflows).
- External LMS/CRM/ERP integrations.
- Advanced multi-channel marketing automation (advanced email marketing, social campaigns).
- Native mobile app (current MVP scope is web-based only).

## 2.3 Scope Boundaries
- We Event manages the in-system event process and does not fully replace internal communications.
- Certificate process support is limited to eligibility determination; template generation/issuance may be handled in later phases by each organization.
- Event cover images are basic event metadata (one image per event); this is not a media CMS.
