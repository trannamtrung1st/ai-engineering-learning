# Wireframes

## Wireframe scope

The following low-fidelity wireframes are required for MVP readiness:

- Participant event discovery.
- Participant event detail with registration status panel.
- Participant My Registrations.
- Organizer event setup form.
- Organizer operations dashboard.
- Organizer check-in console.
- Organizer eligibility list with reasons.

## Per-screen required content blocks

### Participant event discovery
- Search/filter row.
- Event cards/list.
- Pagination control below grid (page X of Y, item range).
- Empty state and retry state.

### Participant event detail
- Event metadata header.
- Registration action area.
- Timeline windows block.
- Current status + reason block.

### Participant My Registrations
- Status list (active + past).
- Pagination control below list.
- Quick actions based on status.
- Status explanation drawer or tooltip.

### Organizer event setup
- Step or section navigation.
- Rule-sensitive fields with helper text.
- Save draft and publish controls.

### Organizer operations dashboard
- KPI cards.
- Registration/waitlist/check-in trend blocks.
- Link-outs to detailed operations pages.

### Organizer check-in console
- Search input and quick filters.
- Participant row list with action button.
- Pagination control below row list.
- Result log or recent activity section.

### Organizer eligibility list
- Eligible/NotEligible segmented view.
- Reason column and export action.
- Pagination control below table.
- Filter by attendance/feedback completion.

## Annotation requirements

- Mark primary and secondary actions.
- Mark domain state rendering for each key block.
- Mark loading, empty, and error variants.
- Mark mobile and desktop behavior changes.

## Wireframe quality gate

- Every wireframe must map to at least one user flow in `10-user-flows.md`.
- Every critical action must include failure-state annotation.
- Every status-sensitive area must define the status vocabulary used.
