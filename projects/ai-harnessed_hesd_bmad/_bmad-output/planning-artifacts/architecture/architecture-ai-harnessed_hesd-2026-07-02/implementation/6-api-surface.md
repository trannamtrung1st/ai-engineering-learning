# 6. API Surface

NestJS REST routes under global prefix `/api/v1`. Web client sends Supabase JWT on every request.

| Method | Path | Role | Domain call |
| --- | --- | --- | --- |
| GET | `/api/v1/sessions/:id/qr-token` | instructor | `mintSessionToken` |
| POST | `/api/v1/check-in` | student | `executeCheckIn` |
| POST | `/api/v1/admin/accounts` | admin | `provisionStudent` |
| POST | `/api/v1/admin/rosters/:id/import` | admin | `importRosterCsv` |
| GET | `/api/v1/sessions/:id/export.csv` | instructor | `exportSessionCsv` |

**Convention:** Web pages call API via a thin `lib/api-client.ts` fetch wrapper that attaches the session token. No domain Server Actions or Next.js Route Handlers for mutations.

All controllers use `@UseGuards(AuthGuard, RolesGuard)` before invoking domain use-cases (AD-7, AD-15).
