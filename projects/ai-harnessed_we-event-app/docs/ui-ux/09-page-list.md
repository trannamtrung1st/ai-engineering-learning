# Page List

## Shared pages

- Sign-in page (`/login`) — shared across roles; email and password.
- Sign-up page (`/signup`) — participant self-registration; creates `Participant` role only.
- Access denied page (`/access-denied`).
- Not found page.
- Generic error/recovery page.

Login and signup are dedicated routes — not inline ID forms inside participant/organizer shells.

## Participant pages

### Event discovery
- Browse list with search and basic filters.
- Surface event availability and registration status.
- Paginated card grid with cover image thumbnail (16:9); fallback illustration when no cover.
- Changing filters resets to page 1.

### Event detail
- Display event information, cover image hero, windows, and current action.
- Show status-dependent CTA and explanation.

### My registrations
- List current and past registrations with status timeline.
- Quick access to check-in or feedback when applicable.
- Paginated status list (server-driven; default `pageSize` 20).

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

### Event management
- Event list (paginated table).
- Create/edit event form with cover image upload (file picker, preview, replace, remove).
- Publish/pause controls.

### Operations dashboard
- KPI blocks (registrations, waitlist, check-ins, feedback, eligibility).
- Drill-down links to detailed views.

### Registration and waitlist management
- Search/filter participants.
- Waitlist queue and promotion visibility.
- Paginated participant and waitlist tables.

### Check-in operations console
- Event check-in list.
- Staff and method audit markers.
- Paginated attendance rows.

### Eligibility management
- Eligible and not-eligible lists.
- Reason visibility and export trigger.
- Paginated segmented lists (order preserved across pages).

### Governance pages
- Audit log history.
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
