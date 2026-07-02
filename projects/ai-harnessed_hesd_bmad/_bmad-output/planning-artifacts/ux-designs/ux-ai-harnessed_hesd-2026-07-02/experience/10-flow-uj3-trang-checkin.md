# Flow UJ-3 — Trang checks in from her phone

**Persona:** Trang (Student)  
**PRD ref:** UJ-3

## Steps

1. Trang scans projected QR with phone camera → mobile web opens check-in URL.
2. System verifies session **Active**; if not, shows closed/scheduled message (no login yet).
3. Trang signs in with provisioned email/password.
4. If first login → password change screen (blocks until done).
5. GPS permission prompt with Vietnamese explanation.
6. Trang taps **Điểm danh**.
7. System validates: auth → token → roster → not checked in → geofence.
8. **Climax:** Success screen — session name, timestamp, green status band.

## Failure branches

Each reason code maps to dedicated copy + one recovery action (retry GPS, scan again, contact instructor). See `2-voice-and-tone.md` for codes.

## Surfaces touched

- Check-in entry
- Sign-in
- First-login password change
- GPS permission
- Check-in outcome

## Related

- `6-accessibility-floor.md` (WCAG AA scope)
- `../design/7-components.md` (primary button, status badges, card)
