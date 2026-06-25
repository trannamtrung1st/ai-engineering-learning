# Accessibility Basics

## MVP accessibility baseline

- Full keyboard access for critical workflows:
  - registration
  - check-in
  - feedback
  - organizer operational tasks
- Visible focus indicators on all actionable elements.
- Proper label and description mapping for form fields.
- Error text programmatically associated with invalid fields.
- Dynamic status updates announced through aria-live regions.
- Sufficient contrast for text, icons, and status markers.
- No color-only communication for important states.

## Semantic structure requirements

- Logical heading hierarchy per page.
- Landmark usage (`header`, `nav`, `main`, `footer`).
- Table semantics for operational lists.
- Button/link semantics must match behavior.

## Form accessibility standards

- Required fields clearly marked and announced.
- Validation timing should not overwhelm screen reader users.
- Errors should be concise and actionable.
- Group related controls with fieldsets where needed.

## Interaction accessibility standards

- Modal dialogs trap focus and restore focus on close.
- Escape key support for dismissible overlays.
- Sufficient tap target sizes for mobile interactions.
- Avoid time-sensitive interactions without clear countdown/expiry hints.

## Accessibility testing checklist

- Keyboard-only walkthrough for participant and organizer core flows.
- Screen reader checks on registration, check-in, and feedback forms.
- Contrast checks for all domain status badges.
- Zoom and reflow verification at 200%.
- Reduced motion preference verification.

## Known MVP risk areas to monitor

- Data-dense organizer tables may require extra labeling on small screens.
- Near real-time updates can be noisy for assistive tech if announcements are not throttled.
- Status badge overload can reduce clarity if icon/text pairing is inconsistent.
