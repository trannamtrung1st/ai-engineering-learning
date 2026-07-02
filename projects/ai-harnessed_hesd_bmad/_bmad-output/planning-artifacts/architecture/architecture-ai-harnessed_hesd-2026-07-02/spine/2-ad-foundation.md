# 2. Foundation ADs

## AD-1 — Split-stack monorepo, role-vertical web slices

- **Binds:** all
- **Prevents:** Domain logic split across Next.js Server Actions and a separate API with diverging check-in rules.
- **Rule:** One repo. **Web** = Next.js at repo root (`app/(admin)/`, `app/(instructor)/`, `app/(student)/`) — UI and route guards only. **API** = NestJS in `api/` — all domain use-cases. Web calls API over HTTP; no `lib/domain/` on the web side.

## AD-2 — Starters: Supabase Next.js + NestJS CLI

- **Binds:** all
- **Prevents:** Hand-rolled session/auth wiring incompatible with Supabase SSR patterns; ad-hoc Express API.
- **Rule:** Web bootstrapped with `create-next-app -e with-supabase` — keep `@supabase/ssr` cookie auth and `middleware.ts` session refresh. API bootstrapped with `nest new api` (NestJS 11). Extend — do not replace — web auth plumbing.

## AD-3 — API-only mutation path

- **Binds:** CAP-3, CAP-4, CAP-6, CAP-7, CAP-8, CAP-10
- **Prevents:** Client bypass of validation sequence or forged attendance writes via web Server Actions.
- **Rule:** All writes to `attendance_records`, `check_in_attempts`, `session_tokens`, rosters, and accounts go through **NestJS controllers** invoking `api/src/domain/` use-cases. Web sends `Authorization: Bearer <supabase_access_token>` on every mutating request. Clients never call Drizzle or Supabase `.insert/.update/.delete` on domain tables.

## AD-15 — NestJS modular API backend

- **Binds:** all API work
- **Prevents:** Ad-hoc route handlers, inconsistent module boundaries, missing guards.
- **Rule:** NestJS 11 in `api/`. Modules by bounded context: `check-in`, `sessions`, `accounts`, `rosters`, `attendance`, `export`. Controllers are thin; domain use-cases hold business rules. Global `AuthGuard` validates Supabase JWT; `RolesGuard` enforces `profiles.role`.
