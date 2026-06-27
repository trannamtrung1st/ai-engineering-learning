# Page List

Listing controls per page: [`14-listing-pages-search-filter-sort.md`](14-listing-pages-search-filter-sort.md).

## Shared pages

- Sign-in page (`/login`) — shared across roles; email and password.
- Sign-up page (`/signup`) — participant self-registration; creates `Participant` role only.
- Access denied page (`/access-denied`).
- Not found page.
- Generic error/recovery page.

Login and signup are dedicated routes — not inline ID forms inside participant/organizer shells.

## Participant pages

### Event discovery (`/events`)
- **Search**: debounced `q` (name, location, description).
- **Filter**: event `state` select.
- **Sort**: `startAt:asc` (default) or `updatedAt:desc`.
- Paginated card grid with cover image thumbnail (16:9); fallback illustration when no cover.
- Registration status badge on each card when participant has an active registration.
- Changing search, filter, or sort resets to page 1.

### Event detail (`/events/{eventId}`)
- Display event information, cover image hero, windows, and current action.
- Show status-dependent CTA and explanation.
- When `Waitlisted`: show queue position and promotion expectation copy.

### My registrations (`/registrations`)
- **Filter**: registration `state` select.
- **Sort**: `updatedAt:desc` (default) or `requestedAt:asc`.
- List current and past registrations; `waitlistPosition` when `Waitlisted`.
- Quick access to check-in or feedback when applicable.
- Paginated status list (server-driven; `pageSize` 20).

### Check-in (self-service)
- Event-specific check-in action page.
- Immediate success/failure feedback and reason.

### Feedback submission
- Post-event form with mandatory/optional context.
- Confirmation on successful submission.

### Participation history and eligibility
- Historical outcomes.
- Eligibility results with reason text.
- Paginated outcomes list.

## Organizer Admin pages

### Event management (`/organizer/events`)
- **Search**: debounced `q` (name, location, description).
- **Filter**: event `state` select (includes `Draft`).
- **Sort**: `startAt:asc` (default) or `updatedAt:desc`.
- Paginated table (`pageSize` 20).
- Create/edit event form with cover image upload (file picker, preview, replace, remove).
- Publish/pause controls.

### Operations dashboard (`/organizer/events/{eventId}`)
- KPI blocks (registrations, waitlist, check-ins, feedback, eligibility).
- Drill-down links to detailed views (registrations, waitlist, check-in, eligibility).

### Registration management (`/organizer/events/{eventId}/registrations`)
- **Filter**: registration `state` select (includes `Waitlisted`).
- **Sort**: server default `updatedAt:desc`; optional sort select future.
- Waitlist position column for `Waitlisted` rows.
- Status history dialog per row.
- Paginated table (`pageSize` 20).

### Waitlist management (`/organizer/events/{eventId}/waitlist`)
- **Sort**: locked FIFO (`position:asc`); subtitle “FIFO order.”
- Columns: position, participant, status, enqueued time.
- No search/filter in MVP (future: participant search).
- Paginated table (`pageSize` 20).

### Check-in operations console (`/organizer/events/{eventId}/check-in`)
- **Sort**: `checkinAt:desc` (server default).
- Staff check-in row action with audit metadata.
- Search/quick filters: future scope.
- Paginated attendance rows (`pageSize` 20).

### Eligibility management (`/organizer/events/{eventId}/eligibility`)
- **Filter**: segmented tabs / `eligibility` param (`Eligible`, `NotEligible`, `PendingEvaluation`, `Revoked`).
- **Sort**: `participantId:asc` (server default).
- Reason column and export action.
- Paginated table (`pageSize` 20).

### Governance pages
- Audit log history — filter by `entityType` / `entityId`; sort `createdAt:desc`.
- Export center.
- Paginated audit log table.

## Organizer Staff pages

- Assigned events list (paginated).
- Check-in console for assigned scope.
- Limited participant lookup tools.

## Routing guidance

- Participant and organizer areas should be clearly separated.
- Route guards should enforce authentication, role, and event scope before render.
- Unauthenticated users redirect to `/login` with return URL preserved.
