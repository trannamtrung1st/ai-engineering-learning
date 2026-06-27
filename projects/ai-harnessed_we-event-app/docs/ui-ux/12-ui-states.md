# UI States

## Data states

- `loading`: skeletons/placeholders; no abrupt layout shift.
- `success-with-data`: fully interactive content.
- `success-empty`: informative empty state with next action.
- `partial-error`: show unaffected modules and isolate failed module.
- `fatal-error`: dedicated error block and retry option.

## Action states

- `idle`
- `hover`
- `focus-visible`
- `pressed`
- `disabled`
- `submitting`
- `success`
- `failure`

Buttons and form controls must consistently map to this state model.

## Domain states (required visual mapping)

### Event
- Draft
- Published
- RegistrationOpen
- RegistrationClosed
- InProgress
- Completed
- Archived
- Cancelled

### Registration
- Requested
- Registered
- Waitlisted
- Rejected
- CancelledByUser
- CancelledByOrganizer
- CheckedIn
- Attended
- Absent
- Expired

### Eligibility
- PendingEvaluation
- Eligible
- NotEligible
- Revoked

## State-to-UX rendering rules

- Every non-terminal status should provide a likely next status hint where possible.
- Terminal statuses must clearly indicate if user can take further actions.
- Status color cannot be the only indicator; always include text labels.
- Critical status transitions should show timestamp context.

## Listing-specific empty and filter-empty copy

| Screen | Empty (no data) | Filter-empty (no matches) |
|--------|-----------------|---------------------------|
| Event discovery | “No events available” | “No events match your filters” + Clear filters |
| My registrations | “No registrations yet” + link to browse events | “No registrations match this status” + reset filter |
| Organizer waitlist | “Waitlist is empty” | N/A (no filter in MVP) |
| Organizer registrations | “No registrations” | “No registrations match this state” + reset filter |

### Waitlisted row rendering (lists)
- Badge: `Waitlisted` semantic color.
- Secondary line: `Queue position: {n}` with helper text on detail views.
- Quick actions: cancel when policy allows; no check-in or feedback links.

## State test checklist

- Registration outcome transitions are reflected in event detail and My Registrations.
- Waitlist promotion transition updates both participant and organizer views.
- Check-in success/failure transitions are visible immediately in console and history.
- Eligibility transitions include reason details and remain traceable.
