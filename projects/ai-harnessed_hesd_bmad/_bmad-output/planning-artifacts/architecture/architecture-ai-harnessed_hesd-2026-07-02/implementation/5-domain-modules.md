# 5. Domain Modules

| Module | Responsibility | AD |
| --- | --- | --- |
| `lib/domain/check-in/execute-check-in.ts` | Full validation sequence + transaction | AD-5, AD-6, AD-10 |
| `lib/domain/check-in/mint-session-token.ts` | 30s token rotation | AD-4 |
| `lib/domain/check-in/geofence.ts` | Haversine distance check | AD-10 |
| `lib/domain/attendance/manual-override.ts` | Instructor correction + audit | AD-3, AD-11 |
| `lib/domain/accounts/provision-student.ts` | Admin API user creation | AD-9 |
| `lib/domain/rosters/import-csv.ts` | Append/replace modes (RD-2) | AD-3 |
| `lib/domain/sessions/` | Session CRUD, activate, geofence config | AD-1, AD-3 |
| `lib/domain/export/csv-export.ts` | Post-session export | AD-3 |

Domain modules must not import from `app/`. Infrastructure access only via `lib/infra/`.
