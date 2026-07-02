# 7. Testing Focus

Add tests when implementing — priority order:

| Priority | Scenario | Layer |
| --- | --- | --- |
| P0 | `executeCheckIn` rejects expired token, off-roster, duplicate, outside geofence | API unit/integration |
| P0 | Unique constraint prevents double check-in under concurrent POSTs | API integration (compose profile) |
| P1 | QR token rotates; old token rejected after expiry | API integration |
| P1 | RolesGuard blocks cross-role endpoints | API integration |
| P2 | CSV import append vs replace modes | API integration |

**Integration tests:** run against `docker compose --profile integration up`; fresh DB per CI job.

**E2E:** deferred — Playwright when first E2E story starts (`spine/11-deferred.md`).
