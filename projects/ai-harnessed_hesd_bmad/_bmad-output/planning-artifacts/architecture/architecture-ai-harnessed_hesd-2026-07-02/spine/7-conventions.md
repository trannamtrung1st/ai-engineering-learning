# 7. Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming (entities) | DB: `snake_case` plural tables (`workshop_sessions`, `attendance_records`). TS domain types: `PascalCase`. IDs: UUID v4 (`uuid` column default `gen_random_uuid()`). |
| Naming (files) | kebab-case files. Web route components under `app/`. API domain: `api/src/domain/<area>/<use-case>.ts`. NestJS modules: `api/src/modules/<area>/`. |
| API base URL | Web reads `NEXT_PUBLIC_API_URL` (default `http://localhost:3001`). All API routes prefixed `/api/v1/` in NestJS global prefix. |
| API errors | Domain returns `Result<T, CheckInErrorCode>`. NestJS `HttpExceptionFilter` maps to `{ error: { code, message } }` with 4xx for validation, 401/403 for auth. |
| Dates | Store UTC `timestamptz`; display in `Asia/Ho_Chi_Minh` for pilot UI. |
| Auth session | Web: Supabase cookie session via `@supabase/ssr`. API calls: `Authorization: Bearer <access_token>` from `supabase.auth.getSession()`. API validates JWT via Supabase JWKS. |
| CSV import/export | Papa Parse in API; UTF-8 with BOM for Excel compatibility on export. |
| UI | Neobrutalism tokens from UX spine; load `.agents/skills/neobrutalism-design-system` before UI work. |
| Logging | `console` structured JSON in API domain use-cases; no APM in MVP. |
| Docker | `docker compose --profile local up` for dev DB+API; `--profile integration` for test runs. |
