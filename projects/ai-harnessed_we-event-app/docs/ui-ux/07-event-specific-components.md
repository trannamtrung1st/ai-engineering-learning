# Event-specific Components

## Participant-facing components

### Event card
- Fields: cover image thumbnail (16:9), title, date/time, location, organizer, capacity hint, registration status.
- Actions: view details, register (if available), view my status.
- States: registration open, full with waitlist, closed, canceled.
- Cover image: use `next/image`; show neutral placeholder when `coverImageUrl` is absent.

### Event detail header
- Fields: cover image hero, event metadata, timeline windows, seat status, policy hints.
- Primary action changes by user state (`Register`, `Cancel registration`, `Check in`, `Submit feedback`).

### Registration status panel
- Displays current status and reason.
- Includes timestamp of latest status change.
- Provides contextual next step.

## Organizer-facing operational components

### Capacity meter
- Shows `Registered / Capacity`.
- Shows waitlist count.
- Warns when nearing capacity threshold.

### Waitlist queue panel
- Ordered queue list (default FIFO).
- Highlights promoted entries.
- Shows reason when promotion is blocked by rule/policy.
- Paginated; queue position order preserved across pages.

### Check-in console row item
- Participant identity summary.
- Eligibility for check-in (valid/invalid window).
- Action outcome with audit metadata (method, actor, timestamp).

### Feedback completion tracker
- Completion ratio.
- Mandatory feedback outstanding count.
- Quick filter for pending participants.

### Eligibility result panel
- Displays `Eligible` / `NotEligible` with reason tags.
- Supports organizer review/export context.
- Indicates post-finalization override markers (if any).
- Paginated list; segmented eligible/not-eligible views preserve sort order across pages.

### Audit timeline
- Shows critical rule/config changes and major lifecycle transitions.
- Includes actor, timestamp, and change summary.
- Paginated log table for long histories.

## Domain status badge system

All domain state families use distinct semantic colors — not outline-only chips.

### Event lifecycle colors

| State | Token | Visual intent |
|---|---|---|
| Draft | `color.status.draft` | Neutral gray — not visible to participants |
| Published | `color.status.published` | Blue — announced, registration not yet open |
| RegistrationOpen | `color.status.registrationOpen` | Green — actionable registration |
| RegistrationClosed | `color.status.registrationClosed` | Amber — closed, awaiting event start |
| InProgress | `color.status.inProgress` | Teal — live event |
| Completed | `color.status.completed` | Slate — finished, feedback may be open |
| Archived | `color.status.archived` | Muted slate — read-only history |
| Cancelled | `color.status.cancelled` | Red — event will not take place |

### Registration and eligibility colors

- Registration states: Requested, Registered, Waitlisted, Rejected, CancelledByUser, CancelledByOrganizer, CheckedIn, Attended, Absent, Expired.
- Eligibility states: PendingEvaluation, Eligible, NotEligible, Revoked.
- Terminal registration states (`CancelledByUser`, `CancelledByOrganizer`, `Expired`) use distinct muted tokens — not the same as active states.

Status badges must include tooltip or inline explanation when ambiguity risk is high.
