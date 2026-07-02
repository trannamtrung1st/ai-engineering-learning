# 6. Deployment ADs

## AD-12 — Deployment envelope

- **Binds:** NFR-2; RD-3
- **Prevents:** Undeployable or unseeded pilot; local/CI infra drift.
- **Rule:** **Local:** `docker compose --profile local up` (Postgres + NestJS API per AD-14); web via `npm run dev` on host; Supabase Auth/Realtime via `supabase start` CLI or remote dev project. **Integration/CI:** `docker compose --profile integration up` — isolated DB + API + migrate/seed (AD-14). **Production:** Vercel hosts Next.js web; Supabase hosted provides Postgres, Auth, Realtime; API host TBD (see Deferred). Bootstrap admin via `supabase/seed.sql`. Secrets: `SUPABASE_SERVICE_ROLE_KEY` and `DATABASE_URL` server-only in API; never in client bundle.

## AD-14 — Docker Compose local and integration profiles

- **Binds:** AD-12; all backend development
- **Prevents:** Divergent local dev vs integration-test infrastructure; "works on my machine" DB state.
- **Rule:** Single `docker-compose.yml` at repo root.

| Profile | Services | Purpose |
| --- | --- | --- |
| `local` | `postgres`, `api` | Daily dev; API hot-reload volume mount |
| `integration` | `postgres`, `api`, `migrate` (one-shot) | CI and local integration tests; fresh migrate + seed per run |

Postgres image: `postgres:16`. API `depends_on` postgres healthcheck. Env from `.env` / `.env.local`. Web is **not** required in compose — runs on host against `NEXT_PUBLIC_API_URL=http://localhost:3001` (or compose-mapped port). E2E stack deferred (`spine/11-deferred.md`).
