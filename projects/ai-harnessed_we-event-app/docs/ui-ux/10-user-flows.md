# User Flows

## Flow 0: Account creation and session

1. New user opens sign-up page (`/signup`).
2. User enters email, password, and display name.
3. System creates account with `Participant` role and signs user in (JWT).
4. User is redirected to intended route or participant event discovery.

## Flow 0b: Sign-in and sign-out

1. User opens sign-in page (`/login`).
2. User enters email and password.
3. System validates credentials and issues JWT; client stores token.
4. User accesses protected routes per role.
5. User selects sign out from TopBar user menu; client clears token and redirects to `/login`.

## Flow 1: Participant registration

1. User opens event discovery.
2. User selects an event and reviews event detail.
3. User clicks `Register`.
4. System validates identity, window, duplicate rule, and capacity.
5. System returns outcome:
   - `Registered` (seat confirmed).
   - `Waitlisted` (queue position provided).
   - `Rejected` (reason shown).
6. My Registrations reflects latest status.

## Flow 2: Participant cancellation and waitlist promotion

1. Registered participant initiates cancellation.
2. System checks cancellation policy deadline.
3. If valid, seat is released.
4. System promotes top waitlist participant under configured priority (FIFO default).
5. Both affected users see updated statuses.

## Flow 3: Organizer staff check-in

1. Staff opens assigned event check-in console.
2. Staff identifies participant and triggers check-in.
3. System validates registration and check-in window.
4. System records audit metadata on success.
5. Invalid attempts return reason (out of window, duplicate, or not registered).

## Flow 4: Participant self check-in

1. Participant opens check-in entry page.
2. System verifies event and registration context.
3. User checks in.
4. UI confirms success with timestamp or displays blocking reason.

## Flow 5: Feedback and eligibility

1. Feedback window opens post-event.
2. Participant submits feedback.
3. System marks feedback completion.
4. Eligibility evaluation runs against attendance and feedback requirements.
5. Result shown as `Eligible` or `NotEligible` with reason.

## Flow 6: Organizer governance and reporting

1. Admin reviews dashboard summary.
2. Admin opens eligibility list and audit timeline.
3. Admin exports operational data.
4. Admin traces key status transitions for reporting.

## Edge-case expectations

- Out-of-window registration/check-in attempts are blocked with explicit rationale.
- Network failure during transaction presents retry path without data loss.
- Permission mismatch routes user to access denied with safe fallback navigation.
