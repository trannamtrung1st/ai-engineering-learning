# UI Framework / Tech Stack

## Recommended MVP stack

- Frontend: React + TypeScript.
- Framework: Next.js App Router.
- Styling: Tailwind CSS with CSS variable-driven semantic tokens.
- Components: headless primitives (Radix UI or equivalent) for accessibility.
- Forms: React Hook Form + Zod.
- Server state: TanStack Query.
- Tables and filters: lightweight table utility (TanStack Table or equivalent).
- Charts: minimal chart library for organizer dashboard KPI visualization.

## Why this stack fits We Event

- Supports fast, state-rich interfaces for status-driven workflows.
- Enables strict typing for rule-sensitive domain states.
- Handles near real-time updates needed by check-in and waitlist operations.
- Makes role-based UI composition straightforward.

## Frontend architecture guidelines

### Route strategy
- Public routes for participant discovery and detail.
- Auth-required routes for registration status, check-in, feedback.
- Organizer namespace with role-aware navigation and guard logic.

### State boundaries
- Server authority for registration, check-in, and eligibility states.
- Client-local state only for presentational behavior (modals, sort order, pending input).
- Optimistic updates only for reversible operations and only with robust rollback UI.

### Data refresh behavior
- Event list: periodic refresh during open registration windows.
- Organizer dashboard: shorter refresh interval in event-active windows.
- Check-in console: explicit refresh action + automatic polling while active.

## Technical UX constraints

- Prevent duplicate submissions by disabling CTA while request is in-flight.
- Surface transaction IDs or trace references for failed critical operations.
- Preserve form draft input during non-fatal network errors.
- Provide consistent loading placeholders to avoid layout shift.

## Role and authorization UX contract

- Participant can only act on their own registration data.
- Staff can only see and operate within assigned event scope.
- Admin-only controls require explicit UI segregation and permission checks.

## Observability hooks for UX quality

- Track drop-off points in registration/check-in/feedback flows.
- Track repeated validation errors to identify unclear form guidance.
- Track failure reasons by action type to improve inline messaging.
