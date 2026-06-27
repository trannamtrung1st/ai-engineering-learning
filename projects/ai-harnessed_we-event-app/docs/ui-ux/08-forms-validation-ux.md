# Forms & Validation UX

## Form architecture

### Event setup flow (Organizer Admin)
- Section 1: basic event details.
- Section 2: capacity and waitlist policy.
- Section 3: registration window.
- Section 4: check-in window and method options.
- Section 5: feedback and certificate rule settings.

Use progressive disclosure to avoid overwhelming users with advanced options.

## Validation model

### Validation levels
- Field-level validation for format and required input.
- Cross-field validation for window logic and rule coherence.
- Server-side validation for business rule enforcement.

### Rule-sensitive validations
- Duplicate registration prevention.
- Registration timing validity.
- Capacity and waitlist consistency.
- Check-in window validity.
- Mandatory feedback requirement before eligibility finalization.

## Error and guidance patterns

- Inline errors for fixable issues.
- Sticky page-level alert for cross-field or submission failure.
- Keep user input intact after failed submission.
- Provide "how to resolve" message, not only failure reason.

## Action behavior

- Submit button disabled during processing.
- Secondary actions remain available only when safe.
- Retry action appears for transient failures.

## Microcopy standards

- Use concrete language: "Registration is closed for this event" instead of "Action not allowed".
- Include policy references where useful (for organizer screens).
- Avoid generic error identifiers in user-facing text.

## Validation QA scenarios

- Attempt registration outside registration window.
- Attempt duplicate registration for same event.
- Attempt second check-in for same registration.
- Submit feedback outside configured feedback window.
- Save event rules with conflicting time windows.
