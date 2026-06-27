# Common UI Components

## Component catalog (MVP)

- Buttons
- Inputs (text, number, datetime, textarea)
- Select/combobox
- Checkbox/radio/toggle
- Badge/chip
- Alerts/toasts
- Modal/dialog
- Tabs
- Table
- Pagination
- Empty state
- Skeleton/loading
- Tooltip

## Behavior contracts

### Buttons
- Primary button: single main action per section.
- Disable while request is in-flight.
- Danger button requires explicit confirmation for destructive effects.

### Inputs and controls
- Show validation as user moves out of field, not on every keystroke by default.
- Keep helper and error text in a stable position to reduce layout jump.
- Date/time controls must display timezone context where relevant.

### Alerts and toasts
- Toast: short success/info notifications for non-blocking outcomes.
- Inline alert: blocking or context-critical failures.
- Alerts should include reason and next action, not just "failed".

### Table
- Required features: sort, filter, empty state, pagination.
- Sticky header for long operational lists.
- Row actions must obey role permissions and state constraints.
- When backed by a paginated API, pagination is **server-driven** (fetch one page per request; do not load the full dataset client-side).

### Pagination
- Shows "Page X of Y" and item range (e.g. "Showing 21–40 of 142").
- Prev/next buttons disabled at first/last page; keyboard accessible.
- Resets to page 1 when search, filter, or sort criteria change.
- **Table lists**: use server-driven pagination with API `page`/`pageSize`/`total` metadata.
- **Card grids** (event discovery): same control below the grid; default `pageSize` 12 per `05-api-design.md`.

### FilterBar
- Sticky row below page header on list-heavy screens ([`06-app-layout-components.md`](06-app-layout-components.md)).
- Groups search input, filter select(s), and sort select (where applicable).
- On viewports below tablet: may collapse to a single “Filters” trigger opening a drawer.
- Changing any control resets pagination to page 1.

### SortSelect
- Maps to API `sort` query param as `field:asc` or `field:desc`.
- Used on participant event discovery, organizer events, and My Registrations in MVP.
- Label + accessible name required (e.g. “Sort by”).
- Waitlist and eligibility pages use fixed server sort only in MVP (no SortSelect).

### Search input (listing)
- Debounce **300ms** before updating API `q` param.
- Used on `GET /events` lists only in MVP.
- “Clear filters” empty-state action resets search, filter, and sort to defaults.

### Modal/dialog
- Use for confirmation or focused secondary tasks.
- Escape and outside click behavior should be predictable and accessible.
- Critical confirmations should summarize consequences clearly.

## Content patterns by domain state

- `Registered`: positive confirmation + next milestone.
- `Waitlisted`: queue position label + explanation that promotion happens when a seat opens (FIFO); cancel option when policy allows.
- `Rejected`: explicit rule reason + what user can do next.
- `Eligible`/`NotEligible`: result + reason trail.

## Component QA checklist

- Keyboard interaction works for all interactive states.
- Disabled states are visually clear and not focus-trapped.
- Error states include both visual and text signals.
- Components render correctly in loading, empty, and failure contexts.
