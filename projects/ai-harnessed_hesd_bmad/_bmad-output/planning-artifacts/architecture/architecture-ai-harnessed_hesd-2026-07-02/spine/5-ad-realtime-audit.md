# 5. Realtime & Audit ADs

## AD-8 — Realtime via Postgres changes

- **Binds:** CAP-5
- **Prevents:** Instructor dashboard requiring manual refresh during live sessions.
- **Rule:** Instructor live session view subscribes to Supabase `postgres_changes` on `attendance_records` filtered by `session_id`. No custom WebSocket server. RLS ensures instructor sees only their sessions.

## AD-11 — Append-only audit log

- **Binds:** CAP-7
- **Prevents:** Missing failure logs or inconsistent audit shape.
- **Rule:** Table `check_in_attempts` is append-only. Every path through `executeCheckIn` and manual override writes one row with `{ student_id, session_id, outcome, failure_reason?, lat?, lng?, source: 'auto'|'manual', actor_id? }`. No updates/deletes in MVP.
