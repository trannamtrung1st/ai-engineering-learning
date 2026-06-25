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

## State test checklist

- Registration outcome transitions are reflected in event detail and My Registrations.
- Waitlist promotion transition updates both participant and organizer views.
- Check-in success/failure transitions are visible immediately in console and history.
- Eligibility transitions include reason details and remain traceable.
