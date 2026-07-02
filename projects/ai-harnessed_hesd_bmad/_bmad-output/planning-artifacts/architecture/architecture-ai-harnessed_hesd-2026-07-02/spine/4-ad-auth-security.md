# 4. Auth & Security ADs

## AD-7 — Role enforcement at edge and API

- **Binds:** CAP-1, CAP-3, CAP-8, CAP-10; FR-3, FR-4
- **Prevents:** Student accessing admin pages or instructor provisioning accounts.
- **Rule:** `profiles.role` enum: `admin | instructor | student`. **Web** middleware guards route prefixes by role. **API** `RolesGuard` on every controller; rejects before domain work. Supabase RLS mirrors role rules on client reads.

## AD-9 — Admin-provisioned accounts only

- **Binds:** CAP-8, CAP-10; FR-1, FR-2, FR-3a; RD-1, RD-3
- **Prevents:** Public self-registration.
- **Rule:** Remove/disable template public sign-up route. Admin creates users via API domain use-case using Supabase Auth Admin API (`service_role` key, API-only). First-login password change enforced in web middleware for students with `must_change_password = true`.

## AD-13 — Data access: Drizzle writes in API only

- **Binds:** all DB access
- **Prevents:** Web writing via Supabase client while API writes via Drizzle with inconsistent authorization.
- **Rule:** Domain **writes** use Drizzle in `api/` with server-only `DATABASE_URL`. API resolves `actor: { id, role }` from validated JWT + profile lookup; use-case asserts permission before write. **Web reads** may use Supabase browser/server client (RLS). Web never imports Drizzle or holds `DATABASE_URL`.
