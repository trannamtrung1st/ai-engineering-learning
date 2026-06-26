# UI Framework / Tech Stack

## Stack

| Concern | Technology |
|---|---|
| Framework | Next.js App Router |
| UI | React + TypeScript |
| Styling | Tailwind CSS + semantic CSS variable tokens |
| Components | Radix UI headless primitives |
| Forms | React Hook Form + Zod |
| Server state | TanStack Query |
| Tables | TanStack Table (server-driven pagination) |
| Charts | Deferred — organizer KPI views use tables/metrics until a chart library is added |

## Why this stack fits We Event

- Supports fast, state-rich interfaces for status-driven workflows.
- Enables strict typing for rule-sensitive domain states via shared `@we-event/domain` types.
- Handles near real-time updates needed by check-in and waitlist operations.
- Makes role-based UI composition straightforward.

## Frontend architecture

### Route strategy
- **Participant namespace** — event discovery, registration status, check-in, feedback, eligibility.
- **Organizer namespace** — event CRUD, operations dashboard, registrations, waitlist, check-in console, audit, eligibility.
- Each namespace has its own layout and auth context.

### API integration
- Browser calls `/api/v1` through the Next.js dev server, which proxies to the backend.
- Role-specific API facades centralize fetch logic and bearer token attachment.

### State boundaries
- **Server authority** for registration, check-in, and eligibility states.
- **TanStack Query** for server/async state; no global client store (Redux/Zustand).
- **React Context** for auth and UI chrome (toasts).
- Client-local state only for presentational behavior (modals, sort order, pending input).
- Optimistic updates only for reversible operations with rollback UI.

### Data refresh behavior
Polling intervals for live surfaces (no WebSockets in MVP):

| Surface | Interval | Rationale |
|---|---|---|
| Event list | 60s | Periodic refresh during open registration |
| Organizer dashboard | 5s | Near real-time during active operations |
| Check-in console | 3s | Fastest refresh while check-in is in progress |

Check-in console also supports explicit manual refresh.

## Technical UX constraints

- Prevent duplicate submissions by disabling CTA while request is in-flight.
- Surface `requestId` from API error envelope for failed critical operations.
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
