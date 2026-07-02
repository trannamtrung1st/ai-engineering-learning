# 2. Cold Start

## Web (existing)

Web is already bootstrapped at repo root via `create-next-app -e with-supabase`.

```bash
npm install
# Supabase Auth/Realtime — pick one:
supabase start          # local CLI stack
# OR use remote dev project URLs in .env.local
```

## API (new)

```bash
npx @nestjs/cli@11 new api --package-manager npm --skip-git
cd api
npm install drizzle-orm drizzle-kit zod papaparse @supabase/supabase-js
```

## Docker Compose (local dev)

```bash
docker compose --profile local up -d   # postgres + api
npm run dev                            # web on :3000
```

## Setup checklist

1. Add `api/` NestJS app with domain tree from `spine/9-structural-seed.md`.
2. Add Drizzle config in `api/` pointing at compose Postgres (`DATABASE_URL`).
3. Add `docker-compose.yml` with `local` and `integration` profiles (AD-14).
4. Run `supabase/seed.sql` for bootstrap admin (RD-3).
5. Remove or guard template `auth/sign-up` route (AD-9).
6. Add `NEXT_PUBLIC_API_URL=http://localhost:3001` to `.env.local`.

## Environment variables (seed)

| Variable | Scope | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | web client | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | web client | Anon/publishable key |
| `NEXT_PUBLIC_API_URL` | web client | NestJS API base URL |
| `SUPABASE_SERVICE_ROLE_KEY` | api only | Admin API, bootstrap |
| `SUPABASE_JWT_SECRET` | api only | JWT validation (local) or JWKS URL |
| `DATABASE_URL` | api only | Drizzle direct Postgres |
| `PORT` | api | API listen port (default 3001) |
