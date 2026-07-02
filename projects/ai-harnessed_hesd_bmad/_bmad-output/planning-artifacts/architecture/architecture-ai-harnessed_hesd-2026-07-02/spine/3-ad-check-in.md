# 3. Check-in ADs

## AD-4 — QR session tokens are server-minted

- **Binds:** CAP-2, CAP-4
- **Prevents:** Client-forged tokens or tokens outliving the 30s window.
- **Rule:** `mintSessionToken(sessionId)` runs in NestJS API only. Token stored in `session_tokens` with `expires_at = now() + 30s`. QR encodes `{ sessionId, token }` as URL to student check-in route. Instructor QR display polls `GET {API_URL}/sessions/:id/qr-token` every **≤5s**. Token is **multi-use** until expiry.

## AD-5 — Check-in validation orchestrator

- **Binds:** CAP-3, CAP-4
- **Prevents:** Partial writes, wrong validation order, or attendance recorded on failed checks.
- **Rule:** Single entry `executeCheckIn(input)` in `api/src/domain/check-in/`. Runs checks **in order** inside one DB transaction (see spec `check-in-validation.md`): (1) authenticated student, (2) valid unexpired token for session, (3) roster membership, (4) no prior successful check-in, (5) GPS within geofence. On any failure: rollback attendance, append audit row, return typed rejection reason. On success: upsert `attendance_records`, append audit row.

## AD-6 — One successful check-in per student per session

- **Binds:** CAP-4
- **Prevents:** Race-condition duplicate check-ins under concurrent load (NFR-1).
- **Rule:** DB unique constraint on `attendance_records(session_id, student_id)` where `status = 'checked_in'`. Orchestrator checks before insert; constraint is the backstop.

## AD-10 — GPS validated server-side

- **Binds:** CAP-4; NFR-6
- **Prevents:** Client-only geofence bypass.
- **Rule:** Student client sends `{ lat, lng, accuracyM }` with check-in attempt. Server computes haversine distance to session center; pass if `distance <= session.radius_m`. Store raw coords in `check_in_attempts` **only on failure**; never expose other students' coords.
