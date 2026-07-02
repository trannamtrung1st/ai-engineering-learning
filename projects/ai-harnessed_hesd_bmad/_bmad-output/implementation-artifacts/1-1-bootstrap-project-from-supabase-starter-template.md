---
baseline_commit: e80700f4f59db20e92da6615594f25eaebd5c49c
---

# Story 1.1: Bootstrap Project from Supabase Starter Template

Status: done

> **Arch pivot note (2026-07-02):** Web bootstrap complete. Drizzle deps at web root superseded by Story **1.1b** (move to `api/`). See sprint-change-proposal-2026-07-02.md.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want the project scaffolded from the official Supabase + Next.js starter with required dependencies,
so that auth plumbing, SSR patterns, and deployment envelope are correct from day one.

## Acceptance Criteria

1. **Given** a greenfield workspace **When** cold-start commands run (`npx create-next-app -e with-supabase`, install `drizzle-orm@0.45.2`, `drizzle-kit`, `zod`, `papaparse`, `@types/papaparse`) **Then** a Next.js 16.2.9 repo exists with `@supabase/ssr` cookie auth and session-refresh middleware/proxy preserved from the template.
2. **And** role route folders exist under `app/(admin)/`, `app/(instructor)/`, `app/(student)/` per AD-1 (with minimal placeholder `layout.tsx` or `page.tsx` so routes compile).
3. **And** environment variable placeholders are documented for `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and `DATABASE_URL`.

## Tasks / Subtasks

- [x] Scaffold Next.js + Supabase app into workspace root (AC: #1)
  - [x] Run official starter; merge into `ai-harnessed_hesd/` without overwriting `_bmad/`, `_bmad-output/`, `.agents/`, `docs/`, `raw/`
  - [x] Verify `package.json` shows Next.js 16.2.x and `@supabase/ssr`
  - [x] Preserve template session refresh (`middleware.ts` or `proxy.ts` — see Dev Notes)
- [x] Install domain dependencies (AC: #1)
  - [x] `npm install drizzle-orm@0.45.2 drizzle-kit zod papaparse`
  - [x] `npm install -D @types/papaparse`
- [x] Create role-vertical route groups (AC: #2)
  - [x] `app/(admin)/` with placeholder page
  - [x] `app/(instructor)/` with placeholder page
  - [x] `app/(student)/` with placeholder page
  - [x] Keep template `app/auth/` routes intact (login flow; sign-up removal is Story 1.3)
- [x] Document environment variables (AC: #3)
  - [x] Update `.env.example` (or create `.env.local.example`) with all four required vars and scope notes
  - [x] Add short `README.md` section: local setup, Supabase dashboard links, server-only vs public keys
- [x] Smoke-verify scaffold (AC: #1)
  - [x] `npm run build` succeeds (env vars may be dummy for build if template allows)
  - [x] `npm run dev` starts without crashing

## Dev Notes

### Epic Context

Epic 1 delivers **Platform Foundation & Secure Access**. This story is the **first** — no prior implementation stories exist. Subsequent stories in order:

| Story | Scope (do NOT implement here) |
|-------|-------------------------------|
| 1.2 | Drizzle schema, migrations, `profiles` table, `supabase/seed.sql` bootstrap admin |
| 1.3 | Role middleware guards, `requireRole()`, disable public sign-up, RLS |
| 1.4 | Student `must_change_password` gate |
| 1.5 | Neobrutalism design system + staff app shell |

### Critical: Non-Empty Workspace

The workspace root already contains BMad planning artifacts (`_bmad/`, `_bmad-output/`, `.agents/`, `docs/`, `raw/`). **`create-next-app` will refuse a non-empty directory.**

**Recommended approach:**

```bash
# From a temp directory
cd /tmp
npx create-next-app@latest hesd-scaffold -e with-supabase --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*"

# Copy scaffold into project root (preserve existing folders)
rsync -av hesd-scaffold/ /Users/trungtran/MyPlace/Personal/Learning/ai-engineering-learning/projects/ai-harnessed_hesd/ \
  --exclude node_modules --exclude .git

cd /Users/trungtran/MyPlace/Personal/Learning/ai-engineering-learning/projects/ai-harnessed_hesd
npm install
```

Adjust flags to match whatever the interactive starter prompts; the critical invariant is **`-e with-supabase`** (AD-2).

**End state:** Next.js app files (`app/`, `lib/`, `middleware.ts` or `proxy.ts`, `package.json`, etc.) live at **workspace root**, not in a nested `hesd-attendance/` subfolder. Architecture doc uses `hesd-attendance/` as a logical product name; this repo path is `ai-harnessed_hesd/`.

### Preserve Template Auth Plumbing (AD-2)

- **Do not** replace `@supabase/ssr` cookie session handling.
- **Do not** remove or gut the template's session-refresh entry point.
- Template ships `lib/supabase/server.ts`, `lib/supabase/client.ts`, and a root `middleware.ts` (or `utils/supabase/middleware.ts` helper) that calls `supabase.auth.getUser()` to refresh cookies.

**Next.js 16 note:** Next.js 16 deprecates `middleware.ts` in favor of `proxy.ts` (export `proxy` instead of `middleware`). The official `with-supabase` example may still ship `middleware.ts` on Next 16 — **keep whichever file the template generates** and preserve its session-refresh logic. Do not rename unless the template already did. Role-based route protection is **Story 1.3**; this story only preserves session refresh.

### Role Route Folders (AD-1)

Create route groups matching `spine/9-structural-seed.md`. Placeholder only — no auth guards yet:

```text
app/
  (admin)/
    layout.tsx          # minimal shell placeholder
    page.tsx            # "Admin — coming soon"
  (instructor)/
    layout.tsx
    page.tsx
  (student)/
    layout.tsx
    page.tsx
  auth/                 # from template — keep as-is
  api/                  # create empty or omit until later stories
```

Future nested routes (do **not** create now unless needed for compile): `(admin)/accounts/`, `(instructor)/sessions/`, `(student)/check-in/`, etc.

### Environment Variables

| Variable | Scope | Purpose |
|----------|-------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | client | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | client | Anon/publishable key (template may name this `NEXT_PUBLIC_SUPABASE_ANON_KEY` — **standardize on `PUBLISHABLE_KEY`** per architecture; map in `.env.example` comments) |
| `SUPABASE_SERVICE_ROLE_KEY` | **server only** | Admin API, bootstrap seeding (Story 1.2) |
| `DATABASE_URL` | **server only** | Drizzle Postgres connection (Story 1.2); use Supabase transaction pooler `:6543` at runtime |

**Security (AD-3, implementation rules):** Never expose `SUPABASE_SERVICE_ROLE_KEY` or `DATABASE_URL` in client bundles or `NEXT_PUBLIC_*` vars.

Document in `.env.example`:

```bash
# Public (safe for browser)
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=

# Server-only — never prefix with NEXT_PUBLIC_
SUPABASE_SERVICE_ROLE_KEY=
DATABASE_URL=
```

### Dependencies (Pinned Versions)

| Package | Version | Notes |
|---------|---------|-------|
| Next.js | 16.2.9 | From starter; verify in `package.json` |
| drizzle-orm | **0.45.2** (exact) | Per architecture stack |
| drizzle-kit | 0.45.x | Pair with drizzle-orm 0.45.2 |
| zod | 3.x | Validation (used from Story 1.2+) |
| papaparse | 5.x | CSV import/export (Epic 2+) |
| @types/papaparse | latest dev | TypeScript types |

**Also needed in Story 1.2 (optional to install now):** `postgres` driver for Drizzle + `dotenv` for drizzle-kit scripts.

```bash
npm install drizzle-orm@0.45.2 drizzle-kit zod papaparse
npm install -D @types/papaparse
```

### What This Story Does NOT Include

- Drizzle `drizzle.config.ts`, schema, or migrations → Story 1.2
- `lib/domain/` use-case implementations → Stories 1.2+
- `supabase/seed.sql` bootstrap admin → Story 1.2
- Role middleware / `requireRole()` → Story 1.3
- Removing `auth/sign-up` → Story 1.3
- Neobrutalism UI / design tokens → Story 1.5
- Playwright or test framework → deferred (`spine/11-deferred.md`)

### Architecture Compliance

| AD / Rule | Application in this story |
|-----------|---------------------------|
| AD-1 | Create `(admin)`, `(instructor)`, `(student)` route groups |
| AD-2 | Bootstrap via `create-next-app -e with-supabase`; preserve SSR auth |
| AD-3 | No client-side domain writes (N/A yet — no domain code) |
| AD-12 | Vercel + Supabase hosted; env vars documented for deploy |
| Conventions (`spine/7-conventions.md`) | kebab-case files; `lib/domain/<area>/` reserved for later |

### File Structure After Completion

```text
ai-harnessed_hesd/                  # workspace root
  app/
    (admin)/...
    (instructor)/...
    (student)/...
    auth/...                        # template login routes
  lib/
    supabase/...                    # from template
    # lib/domain/ and lib/infra/db/ — Story 1.2
  components/                       # template shadcn primitives — keep
  middleware.ts or proxy.ts         # session refresh preserved
  supabase/                         # create folder; migrations/seed in 1.2
  .env.example                      # documented vars
  package.json
  _bmad/                            # untouched
  _bmad-output/                     # untouched
  docs/ui-ux/design-system/         # untouched — used in Story 1.5
```

### Testing Requirements

- No automated tests required for this bootstrap story (`implementation/7-testing-focus.md` defers test stack).
- Manual smoke: `npm run build`, `npm run dev`, confirm starter login page loads.
- Do not add Playwright until a story explicitly requires E2E.

### Latest Technical Notes (2026)

1. **Next.js 16 `proxy.ts`:** If the starter targets Next 16, watch for `middleware.ts` → `proxy.ts` migration. Preserve session-refresh behavior; role guards come later.
2. **Supabase env naming:** Official template uses `NEXT_PUBLIC_SUPABASE_ANON_KEY`; architecture standardizes on `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. Pick one name in code and document the alias in `.env.example`.
3. **Drizzle + Supabase pooler:** When wiring Drizzle (Story 1.2), use transaction pooler port `6543` with `prepare: false` for serverless; use direct/session connection for `drizzle-kit migrate`.
4. **Node.js:** Requires 20.9+ per `spine/8-stack.md`.

### Project Context Reference

- Global agent rules: `_bmad-output/project-context.md`
- Architecture router: `_bmad-output/planning-artifacts/architecture/architecture-ai-harnessed_hesd-2026-07-02/index.md`
- Cold start: `.../implementation/2-cold-start.md`
- Structural seed / source tree: `.../spine/9-structural-seed.md`
- Stack versions: `.../spine/8-stack.md`

### References

- [Source: epics/epics-ai-harnessed_hesd-2026-07-02/epic-1-platform-foundation-secure-access.md#Story-1.1]
- [Source: architecture/.../spine/2-ad-foundation.md#AD-1, AD-2]
- [Source: architecture/.../implementation/2-cold-start.md]
- [Source: architecture/.../spine/9-structural-seed.md#Source-tree]
- [Source: architecture/.../spine/8-stack.md]
- [Source: _bmad-output/project-context.md]

## Dev Agent Record

### Agent Model Used

gpt-5.3-codex

### Debug Log References

- 2026-07-02: Marked story in-progress and captured baseline commit.
- 2026-07-02: Scaffolded via `create-next-app -e with-supabase` in `/tmp/hesd-scaffold`, rsync'd into workspace root preserving BMad artifacts.
- 2026-07-02: Used isolated npm cache (`/tmp/hesd-npm-cache`) to avoid host cache permission errors.
- 2026-07-02: Preserved template `proxy.ts` + `lib/supabase/proxy.ts` session refresh (Next.js 16 proxy pattern).
- 2026-07-02: Role placeholders at `/admin`, `/instructor`, `/student` to avoid conflict with template `/` home page.
- 2026-07-02: `npm run build` passed; `npm run dev` returned HTTP 200 for `/`, `/auth/login`, `/admin`.

### Completion Notes List

- Bootstrapped Next.js 16.2.10 + Supabase SSR starter at workspace root with `@supabase/ssr@0.12.0`.
- Installed domain deps: `drizzle-orm@0.45.2`, `drizzle-kit`, `zod`, `papaparse`, `@types/papaparse`.
- Added role route groups `(admin)`, `(instructor)`, `(student)` with layout + placeholder pages; kept `app/auth/*` intact.
- Documented all four env vars in `.env.example` and added HESD local setup section to `README.md`.
- Created `supabase/` folder placeholder for Story 1.2 migrations/seed.

### File List

- `.env.example`
- `.gitignore`
- `README.md`
- `components.json`
- `eslint.config.mjs`
- `next.config.ts`
- `next-env.d.ts`
- `package.json`
- `package-lock.json`
- `postcss.config.mjs`
- `proxy.ts`
- `tailwind.config.ts`
- `tsconfig.json`
- `app/(admin)/layout.tsx`
- `app/(admin)/admin/page.tsx`
- `app/(instructor)/layout.tsx`
- `app/(instructor)/instructor/page.tsx`
- `app/(student)/layout.tsx`
- `app/(student)/student/page.tsx`
- `app/auth/**` (template auth routes)
- `app/layout.tsx`
- `app/page.tsx`
- `app/protected/**`
- `components/**`
- `lib/supabase/client.ts`
- `lib/supabase/proxy.ts`
- `lib/supabase/server.ts`
- `lib/utils.ts`
- `supabase/.gitkeep`

### Change Log

- 2026-07-02: Story 1.1 — bootstrapped Supabase + Next.js starter, domain dependencies, role route placeholders, env documentation, smoke verification.
