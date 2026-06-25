# Design Overview

> Harness FrontendAgent work must meet `00-production-ui-quality-bar.md` before merge-ready review.

## Product context

We Event is a web-based platform for educational organizations to manage the event lifecycle from setup to certificate eligibility evaluation. UX must reduce operational ambiguity caused by fragmented tools and make status transitions understandable for all roles.

## UX objectives

- Participant journey is short and clear: discover, register, check in, submit feedback, view result.
- Organizer journey is controlled and auditable: configure rules, monitor operations, export outcomes.
- Critical actions always provide immediate result feedback with explicit reason.
- Capacity, waitlist, and eligibility are transparent and traceable.

## Primary users and UX needs

### Participant
- Needs a simple decision path from event detail to registration outcome.
- Needs confidence in current status (`Registered`, `Waitlisted`, `Rejected`).
- Needs clear timing guidance for check-in and feedback windows.
- Needs reason-based eligibility outcomes after event completion.

### Organizer Admin
- Needs predictable event configuration UX with low setup errors.
- Needs real-time operational visibility to avoid manual reconciliation.
- Needs data export and rule-change traceability for governance.

### Organizer Staff
- Needs fast, low-friction check-in operations with minimal screen complexity.
- Needs clear handling for invalid or duplicate check-in attempts.

## Product UX principles

- **Rule transparency**: expose why the system accepted, queued, or blocked an action.
- **State-first UI**: every major screen is organized around current domain state.
- **Action confidence**: disable invalid actions early; explain what to do next.
- **Operational resilience**: make retry and recovery obvious for unstable network conditions.
- **Role safety**: hide or disable unavailable actions to reduce permission mistakes.

## Non-goals for MVP UX

- No payment or ticketing interactions.
- No native mobile-first feature parity requirement (responsive web only).
- No complex external communication automation flows.

## BRD alignment notes

- Registration/capacity UX maps to FR-05..FR-12 and BR-01..BR-09.
- Check-in UX maps to FR-13..FR-17 and BR-10..BR-13.
- Feedback and certificate UX maps to FR-18..FR-21 and BR-14..BR-20.
- Governance UX maps to FR-22..FR-27 and BR-21..BR-22.
