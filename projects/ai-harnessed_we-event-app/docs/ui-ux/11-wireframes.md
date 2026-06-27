# Wireframes

## Wireframe scope

The following low-fidelity wireframes are required for MVP readiness:

- Participant event discovery.
- Participant event detail with registration status panel.
- Participant My Registrations.
- Organizer event setup form.
- Organizer operations dashboard.
- Organizer registrations list.
- Organizer waitlist queue.
- Organizer check-in console.
- Organizer eligibility list with reasons.

## Per-screen required content blocks

### Participant event discovery
- FilterBar: search input, event state filter, sort select (`startAt` / `updatedAt`).
- Event cards/list.
- Pagination control below grid (page X of Y, item range).
- Empty state (“No events match your filters” + Clear filters) and retry state.

### Participant event detail
- Event metadata header.
- Registration action area.
- Timeline windows block.
- Current status + reason block.
- When waitlisted: queue position + promotion expectation note.

### Participant My Registrations
- FilterBar: registration status filter, sort select (`updatedAt` / `requestedAt`).
- Status list (active + past); waitlist position on `Waitlisted` rows.
- Pagination control below list.
- Quick actions based on status.
- Status explanation drawer or tooltip.

### Organizer event setup
- Step or section navigation.
- Rule-sensitive fields with helper text (capacity, waitlist toggle).
- Save draft and publish controls.

### Organizer events list
- FilterBar: search input, event state filter (incl. Draft), sort select.
- Paginated table with lifecycle badges.
- Create event primary action.

### Organizer operations dashboard
- KPI cards.
- Registration/waitlist/check-in trend blocks.
- Link-outs to detailed operations pages (registrations, waitlist, check-in, eligibility).

### Organizer registrations list
- FilterBar: registration state filter.
- Table: participant, status, waitlist #, updated, reason, status-history action.
- Pagination below table.

### Organizer waitlist queue
- Page subtitle: FIFO order preserved across pages.
- Table: position, participant, status, enqueued time.
- No sort control (locked FIFO).
- Empty state: “Waitlist is empty.”
- Pagination below table.

### Organizer check-in console
- Check-in window summary.
- Participant row list with check-in action button.
- Pagination control below row list.
- Search/quick filters: annotate as future if not in MVP wireframe revision.

### Organizer eligibility list
- Eligible/NotEligible segmented view (tabs).
- Reason column and export action.
- Pagination control below table.

## Annotation requirements

- Mark primary and secondary actions.
- Mark domain state rendering for each key block.
- Mark loading, empty, and error variants.
- Mark mobile and desktop behavior changes.
- Mark FilterBar collapse behavior on narrow viewports.

## Wireframe quality gate

- Every wireframe must map to at least one user flow in `10-user-flows.md`.
- Every critical action must include failure-state annotation.
- Every status-sensitive area must define the status vocabulary used.
- Listing screens must reference control matrix in `14-listing-pages-search-filter-sort.md`.
