# Check-In Validation

Load-bearing rules for QR semantics, student check-in eligibility, GPS geofence, and layered fraud reduction.

## QR session token

- The displayed QR encodes a **short-lived multi-use session token** bound to one active workshop session.
- Token lifetime is **30 seconds**; the displayed QR rotates on that interval.
- Multiple students may scan and use the **same token** while it is valid — the QR is projected for the whole room.
- The token is **not** a one-time code for the entire class.

## Per-student uniqueness

- Each student may have **at most one successful check-in** per workshop session.
- Repeat attempts after a successful check-in are rejected and logged.

## GPS geofence (MVP)

- Each session defines a **circular geofence**: center coordinates (latitude/longitude) plus radius in meters.
- **Default radius: 100 m** — suitable for a single classroom or small workshop room.
- **Configurable range: 50–200 m** per session at creation time.
- Check-in succeeds only when the student's device GPS falls inside the circle.
- Instructor sets the center when configuring the session (e.g., venue pin or current location).

## Validation sequence

A check-in attempt succeeds only when **all** checks pass:

| Order | Check | Failure outcome |
|-------|-------|-----------------|
| 1 | Student is authenticated (admin-provisioned account) | Reject; no attendance recorded |
| 2 | QR token is valid and unexpired for the target session | Reject; log attempt |
| 3 | Student is on the session roster | Reject; log attempt |
| 4 | Student has not already checked in to this session | Reject; log attempt |
| 5 | Device GPS falls within the session geofence | Reject; log attempt |

Failed checks do not record attendance. Anomalous or repeated failures are retained in the audit log for instructor review.

## Fraud posture

The system **does not** aim for absolute anti-fraud. It reduces casual cheating through:

- Mandatory login (admin-provisioned accounts)
- Fast-expiring shared QR tokens
- One successful check-in per student per session
- Basic GPS geofence validation
- Audit logging of failed and suspicious attempts
- Manual override by instructor when exceptions occur
