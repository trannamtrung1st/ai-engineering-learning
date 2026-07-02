# 3. Build Order

Recommended phases for solo implementation. Complete each phase before starting the next.

| Phase | Build | Validates |
| --- | --- | --- |
| 0 | `docker-compose.yml` + NestJS `api/` scaffold + Drizzle in API | AD-14, AD-15 |
| 1 | Drizzle schema + migrations for all tables | Entity model (`spine/9-structural-seed.md`) |
| 2 | Auth: API JWT guard + web middleware role guards + password-change gate | FR-3, FR-3a, AD-7, AD-9 |
| 3 | Admin: account provisioning (manual + CSV) | FR-1, FR-2, CAP-10 |
| 4 | Admin: roster CRUD + CSV append/replace | FR-5, FR-6, CAP-8 |
| 5 | Instructor: session CRUD + geofence + activate | FR-7–FR-9, CAP-1 |
| 6 | QR display + token mint API endpoint | CAP-2, AD-4 |
| 7 | Student check-in flow + executeCheckIn | CAP-3, CAP-4, AD-5 |
| 8 | Instructor live dashboard + Realtime subscribe | CAP-5, AD-8 |
| 9 | Manual override + audit viewer | CAP-6, CAP-7 |
| 10 | CSV export | CAP-9 |

Each phase should cite the governing AD IDs in commit messages or story notes for traceability.
