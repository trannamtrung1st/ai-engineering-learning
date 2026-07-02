# 10. Capability → Architecture Map

| Capability / Area | Lives in | Governed by |
| --- | --- | --- |
| CAP-1 Session create/configure | `api/src/domain/sessions/`, `app/(instructor)/sessions/` | AD-1, AD-3, AD-7, AD-15 |
| CAP-2 Dynamic QR | `api/src/domain/check-in/mint-session-token.ts`, `app/(instructor)/sessions/[id]/display/` | AD-4, AD-15 |
| CAP-3 Student check-in flow | `app/(student)/check-in/`, `api/` check-in controller | AD-3, AD-5, AD-9, AD-15 |
| CAP-4 Validation | `api/src/domain/check-in/execute-check-in.ts` | AD-5, AD-6, AD-10 |
| CAP-5 Realtime dashboard | `app/(instructor)/sessions/[id]/live/` | AD-8 |
| CAP-6 Manual override | `api/src/domain/attendance/manual-override.ts` | AD-3, AD-11, AD-15 |
| CAP-7 Audit log | `check_in_attempts` + API domain writers | AD-11 |
| CAP-8 Roster management | `api/src/domain/rosters/`, `app/(admin)/rosters/` | AD-3, AD-7, AD-15 |
| CAP-9 CSV export | `api/src/domain/export/csv-export.ts` | AD-3, AD-15 |
| CAP-10 Account provisioning | `api/src/domain/accounts/`, `app/(admin)/accounts/` | AD-3, AD-7, AD-9, AD-13, AD-15 |
| Local / integration infra | `docker-compose.yml`, `api/Dockerfile` | AD-12, AD-14 |
