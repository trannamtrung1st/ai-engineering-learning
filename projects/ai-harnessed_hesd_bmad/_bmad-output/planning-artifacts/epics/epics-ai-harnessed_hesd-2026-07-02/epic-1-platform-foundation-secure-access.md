# Epic 1: Platform Foundation & Secure Access

Staff and students can sign in to role-gated surfaces on a deployed, seeded platform.

### Story 1.1: Bootstrap Project from Supabase Starter Template

As a developer,
I want the project scaffolded from the official Supabase + Next.js starter,
So that auth plumbing, SSR patterns, and the web deployment envelope are correct from day one.

**Acceptance Criteria:**

**Given** a greenfield workspace
**When** the cold-start command runs (`npx create-next-app -e with-supabase`) for web only
**Then** a Next.js 16.2.9 repo exists with `@supabase/ssr` cookie auth and `middleware.ts` session refresh preserved from the template
**And** role route folders exist under `app/(admin)/`, `app/(instructor)/`, `app/(student)/` per AD-1
**And** environment variable placeholders are documented for `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL`, and API-only `SUPABASE_SERVICE_ROLE_KEY` / `DATABASE_URL` (deferred to Story 1.1b)
**And** domain dependencies (drizzle-orm, drizzle-kit, zod, papaparse) are deferred to Story 1.1b in `api/`

### Story 1.1b: NestJS API and Docker Compose Scaffold

As a developer,
I want a NestJS API and Docker Compose local/integration stack,
So that domain logic and database access follow AD-14 and AD-15 from day one.

**Acceptance Criteria:**

**Given** the web scaffold from Story 1.1
**When** `nest new api` runs (NestJS 11.1.27) and `docker-compose.yml` is added at repo root
**Then** `api/` exists with global prefix `/api/v1`, modules folder, and `AuthGuard`/`RolesGuard` stubs
**And** compose profile `local` starts `postgres:16` + `api` with hot-reload
**And** compose profile `integration` runs migrate/seed one-shot for CI
**And** `drizzle-orm`, `drizzle-kit`, `zod`, `papaparse` are installed in `api/` only — removed from web `package.json`
**And** `.env.example` documents `NEXT_PUBLIC_API_URL`, API-only `DATABASE_URL`, `SUPABASE_JWT_SECRET` or JWKS config
**And** `docker compose --profile local up` + `npm run dev` (web) smoke-verified

### Story 1.2: Profiles Schema and Bootstrap Admin Seed

As an Admin,
I want a bootstrap admin account available after deployment,
So that I can sign in and begin provisioning the pilot without manual database edits.

**Acceptance Criteria:**

**Given** `api/` with Drizzle configured against Postgres (compose local or Supabase pooler)
**When** migrations run from `api/` for the `profiles` table (`id`, `role`, `student_id?`, `full_name`, `must_change_password`)
**Then** `profiles.role` accepts `admin | instructor | student` per AD-7
**And** `supabase/seed.sql` creates one bootstrap Admin profile linked to auth.users (RD-3, AD-12)
**And** Drizzle and `DATABASE_URL` exist only in `api/` per AD-13

### Story 1.3: Role-Based Authentication and Route Protection

As a user with a specific role,
I want to sign in and reach only the surfaces permitted for my role,
So that Students cannot access staff dashboards and Instructors cannot access Admin-only pages.

**Acceptance Criteria:**

**Given** a signed-in user with a `profiles.role` value
**When** they navigate to a route under `app/(admin)/`, `app/(instructor)/`, or `app/(student)/`
**Then** middleware blocks access to route prefixes not matching their role (FR3, AD-7)
**And** NestJS controllers use `AuthGuard` + `RolesGuard` before domain work (AD-7, AD-15)
**And** web `lib/api-client.ts` attaches Supabase `access_token` to API requests
**And** no Next.js Server Actions or Route Handlers perform domain mutations (AD-3)
**And** the template public sign-up route is removed or disabled (AD-9)
**And** Supabase RLS policies mirror role rules on client-readable tables as defense-in-depth

### Story 1.4: Student First-Login Password Change Gate

As a Student with an admin-set or system-generated initial password,
I want to be required to set a new password before accessing check-in,
So that temporary credentials cannot be used indefinitely.

**Acceptance Criteria:**

**Given** a Student profile with `must_change_password = true`
**When** they sign in successfully
**Then** middleware redirects them to the password change screen before any student check-in route (FR3a, UX-DR33)
**And** check-in routes remain blocked until password change completes
**When** the Student submits a valid new password
**Then** `must_change_password` is set to false and an audit log entry is created without storing the password value (FR3a)
**And** the Student can proceed to permitted student routes

### Story 1.5: Design System Foundation and Staff App Shell

As a staff user (Admin or Instructor),
I want a consistent Neobrutalism UI shell with navigation,
So that all subsequent admin and instructor features share the same visual language and layout.

**Acceptance Criteria:**

**Given** the DESIGN spine tokens and `docs/ui-ux/design-system/` modules
**When** the theme foundation is implemented in Tailwind/CSS
**Then** color, typography, spacing, and rounded tokens from `design/index.md` are available application-wide (UX-DR1)
**And** reusable Primary button, Card, and Input components match visual specs (UX-DR2, UX-DR4, UX-DR5)
**And** Admin and Instructor layouts render sidebar navigation at ≥768px and a collapsible drawer below 768px (UX-DR27)
**And** a login page allows Admin, Instructor, and Student sign-in with role-appropriate post-login redirect (FR3)
