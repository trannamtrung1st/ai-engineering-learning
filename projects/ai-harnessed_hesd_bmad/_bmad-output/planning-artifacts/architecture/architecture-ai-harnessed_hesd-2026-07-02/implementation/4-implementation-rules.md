# 4. Implementation Rules

Non-negotiable — violating these breaks the architecture spine.

- **Never** insert into `attendance_records` or `check_in_attempts` outside `api/src/domain/`.
- **Never** mutate domain tables from Next.js Server Actions, Route Handlers, or client Supabase calls.
- **Never** skip a validation step or reorder checks in `executeCheckIn` (AD-5).
- **Never** expose `SUPABASE_SERVICE_ROLE_KEY` or `DATABASE_URL` to web/client code.
- **Always** apply `AuthGuard` + `RolesGuard` on NestJS controllers before domain work (AD-7, AD-15).
- **Always** use Neobrutalism design-system skill for new UI components.
- **Always** pass `actor: { id, role }` into domain write use-cases (AD-13).
- **Always** run local backend via `docker compose --profile local` or document why not (AD-14).
