---
type: sprint-change-proposal
project: ai-harnessed_hesd
trigger: architecture-spine-update-split-stack
status: approved
approved: 2026-07-02
approved_by: TNT
created: 2026-07-02
author: bmad-correct-course
---

# Sprint Change Proposal — Architecture Pivot to NestJS + Docker Compose

## Section 1: Issue Summary

### Trigger

Architecture spine updated **mid-sprint** from a **Next.js modular monolith** (`lib/domain/` + Server Actions / Route Handlers) to a **split-stack monorepo**:

- **Web:** Next.js (UI, Supabase SSR auth, Realtime subscribe)
- **API:** NestJS 11 in `api/` (domain + REST)
- **Local/CI infra:** Docker Compose profiles `local` + `integration` (AD-14)
- **New ADs:** AD-14 (compose), AD-15 (NestJS)

### Discovery context

| Item | Detail |
|------|--------|
| Triggering story | **1.1** (in `review`) — completed against **old** AD-1/AD-3 |
| When discovered | During `/bmad-architecture update` after web bootstrap landed |
| Evidence | Story 1.1 installed `drizzle-orm` at web root; epics reference `lib/domain/`, Server Actions, `POST /api/check-in` on Next.js; no `api/` or `docker-compose.yml` exists |

### Core problem

**Epics, stories, requirements inventory, and SPEC companions still describe the monolith.** Continuing with Story 1.2+ without course correction would implement the wrong mutation path and duplicate infra assumptions.

### Issue type

**Strategic pivot** (deliberate architecture decision) — not a failed approach or PRD scope change.

---

## Section 2: Impact Analysis

### Checklist summary

| Section | Status | Notes |
|---------|--------|-------|
| 1. Trigger & context | [x] Done | Arch update post–Story 1.1 |
| 2. Epic impact | [x] Done | Epic 1 needs new story; Epics 2–5 AC text stale |
| 3. Artifact conflicts | [x] Done | Epics inventory + stories conflict; arch **already updated**; UX/PRD largely unaffected |
| 4. Path forward | [x] Done | **Direct Adjustment** selected |
| 5. Proposal components | [x] Done | This document |
| 6. Final review | [!] Action-needed | Awaiting user approval |

### Epic impact

| Epic | Can complete as planned? | Change needed |
|------|--------------------------|---------------|
| **Epic 1** Platform Foundation | Partially — 1.1 web scaffold OK | **Add Story 1.1b** (API + compose); **amend 1.2, 1.3** |
| **Epic 2** Admin accounts/rosters | Yes (intent unchanged) | Amend ACs: API calls replace `lib/domain/` Server Actions |
| **Epic 3** Instructor sessions/QR | Yes | Amend ACs: domain paths + QR poll URL → NestJS |
| **Epic 4** Student check-in | Yes | **Amend 4.2, 4.3** heavily (API path, guards) |
| **Epic 5** Live dashboard/export | Yes | Amend override + export to API |
| **Epic 6** Audit | Yes | Minor: audit writes already API-side per AD-11 |
| **New epic?** | No | Phase 0 fits inside Epic 1 |

### Story impact matrix

| Story | Status | Impact |
|-------|--------|--------|
| 1.1 | review | **Close as done** with documented delta (web drizzle deps to remove in 1.1b) |
| **1.1b** | **NEW** | NestJS scaffold + docker-compose |
| 1.2 | backlog | Drizzle/migrations move to `api/` |
| 1.3 | backlog | Web middleware only; API `AuthGuard` + `RolesGuard` |
| 1.4 | backlog | Password-change audit write via API if applicable |
| 1.5 | backlog | No change (UI only) |
| 2.2–2.6 | backlog | Provision/import/roster via API |
| 3.2–3.5 | backlog | Session CRUD + QR token via API |
| 4.2 | backlog | **Major rewrite** — NestJS orchestrator |
| 4.3 | backlog | Client calls `NEXT_PUBLIC_API_URL` |
| 5.2–5.3 | backlog | Override + CSV export via API |
| 6.1 | backlog | Read-only UI; likely unchanged |

### Artifact conflicts

| Artifact | Conflict? | Action |
|----------|-----------|--------|
| **PRD** | No functional conflict | No PRD edit — capabilities unchanged |
| **Architecture spine** | Already resolved | None — source of truth |
| **Epics + stories** | **Yes** | Amend per Section 4 |
| **1-requirements-inventory.md** | **Yes** | Update AD/stack summary |
| **UX spine** | No | Flows unchanged; web still calls "system" |
| **SPEC.md** | No capability conflict | Run `/bmad-spec` to refresh `architecture-diagrams.md` companion |
| **project-context.md** | Already updated | None |
| **sprint-status.yaml** | Out of sync | Add 1.1b entry after approval |
| **Story file 1-1-*.md** | Stale dev notes | Add arch-delta note or close via 1.1b |

### Technical impact

- Remove `drizzle-orm`, `drizzle-kit` from **web** `package.json` (currently installed by 1.1)
- Create `api/` (NestJS 11.1.27), `docker-compose.yml`
- Add `NEXT_PUBLIC_API_URL`, move `DATABASE_URL` to API-only env
- Web gains `lib/api-client.ts` thin fetch wrapper (convention from spine §7)

---

## Section 3: Recommended Approach

### Selected path: **Option 1 — Direct Adjustment** (with no rollback)

| Option | Viable? | Rationale |
|--------|---------|-----------|
| **1. Direct Adjustment** | **Yes** | Story 1.1 web work is reusable; add 1.1b + amend backlog |
| 2. Rollback 1.1 | No | Re-scaffolding web wastes done work; only drizzle deps need moving |
| 3. MVP scope reduction | No | Same MVP; different implementation topology |

**Effort:** Medium (+1 story, ~8 story AC patches, spec companion sync)  
**Risk:** Low–medium (solo builder; compose adds ops surface but AD-14 fixes local/CI drift)  
**Timeline:** +0.5–1 sprint phase for Epic 1 (1.1b before 1.2)

### Sequencing after approval

```
1.1  → done (with note)
1.1b → ready-for-dev (NestJS + compose)  ← NEW, blocks 1.2
1.2  → profiles schema in api/
1.3  → web middleware + API guards
1.4, 1.5 → unchanged intent
Epic 2+ → proceed with amended API paths
/bmad-spec → sync SPEC companion (parallel, non-blocking)
```

---

## Section 4: Detailed Change Proposals

### 4.1 New story — Epic 1

#### Story 1.1b: NestJS API and Docker Compose Scaffold

**Insert after Story 1.1, before Story 1.2.**

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

**Rationale:** AD-14, AD-15, amended AD-3/AD-13. Unblocks all domain stories.

---

### 4.2 Story amendments — Epic 1

#### Story 1.1 — close with delta note

**Section:** Acceptance Criteria #1

**OLD:**
```
When cold-start commands run (..., install drizzle-orm 0.45.2, drizzle-kit, zod, papaparse)
```

**NEW:**
```
When cold-start commands run (npx create-next-app -e with-supabase) for web only
And domain dependencies (drizzle, zod, papaparse) are deferred to Story 1.1b in api/
```

**Section:** Acceptance Criteria #3 — env vars

**ADD:**
```
And NEXT_PUBLIC_API_URL is documented (web → API base URL)
And DATABASE_URL is documented as API-only (not web)
```

**Rationale:** 1.1 delivered web correctly; drizzle at root is superseded by 1.1b cleanup.

---

#### Story 1.2 — Profiles Schema and Bootstrap Admin Seed

**OLD:**
```
Given the scaffolded project with Drizzle configured against Supabase Postgres
...
And domain writes use Drizzle with server-only DATABASE_URL per AD-13
```

**NEW:**
```
Given api/ with Drizzle configured against Postgres (compose local or Supabase pooler)
When migrations run from api/ for the profiles table (...)
...
And Drizzle and DATABASE_URL exist only in api/ per AD-13
And supabase/seed.sql creates bootstrap Admin (unchanged)
```

---

#### Story 1.3 — Role-Based Authentication and Route Protection

**OLD:**
```
And every Server Action and Route Handler calls requireRole(...) before domain work
```

**NEW:**
```
And web middleware guards route prefixes by role (unchanged)
And NestJS controllers use AuthGuard + RolesGuard before domain work (AD-7, AD-15)
And web lib/api-client.ts attaches Supabase access_token to API requests
And no Next.js Server Actions or Route Handlers perform domain mutations (AD-3)
```

---

### 4.3 Story amendments — Epics 2–5 (pattern)

Apply this substitution across affected stories:

| OLD pattern | NEW pattern |
|-------------|-------------|
| `lib/domain/<area>/` | `api/src/domain/<area>/` invoked via NestJS controller |
| Server Action with `requireRole` | Web form → `lib/api-client.ts` → API with JWT; `RolesGuard` on controller |
| `POST /api/check-in` (Next.js) | `POST {API_URL}/api/v1/check-in` (NestJS) |
| `GET /api/sessions/[id]/qr-token` | `GET {API_URL}/api/v1/sessions/:id/qr-token` |
| `GET /api/sessions/[id]/export.csv` | `GET {API_URL}/api/v1/sessions/:id/export.csv` |
| `requireRole('student')` on route handler | `RolesGuard` + `@Roles('student')` on NestJS controller |

#### Story 4.2 — explicit rewrite (highest risk)

**OLD:**
```
When executeCheckIn(input) is invoked from lib/domain/check-in/ via POST /api/check-in with requireRole('student')
```

**NEW:**
```
When executeCheckIn(input) in api/src/domain/check-in/ is invoked via POST /api/v1/check-in
And AuthGuard validates Supabase JWT and RolesGuard enforces student role
```

#### Story 4.3 — client call

**OLD:**
```
Then the client calls POST /api/check-in with sessionId, token, and { lat, lng, accuracyM }
```

**NEW:**
```
Then the client calls POST {NEXT_PUBLIC_API_URL}/api/v1/check-in via lib/api-client.ts with sessionId, token, and { lat, lng, accuracyM }
```

---

### 4.4 Requirements inventory (`1-requirements-inventory.md`)

**OLD stack bullet:**
```
Next.js 16.2.9 modular monolith ... shared logic only in lib/domain/
```

**NEW:**
```
Next.js 16.2.9 web + NestJS 11.1.27 API (api/); domain only in api/src/domain/; Docker Compose profiles local + integration (AD-14)
```

Update AD-1, AD-3, AD-13, API surface, and env var rows to match current spine `8-stack.md`, `6-ad-deployment.md`, `implementation/6-api-surface.md`.

---

### 4.5 SPEC companion (via `/bmad-spec` — not in this PR)

Add architecture spine reference to `SPEC.md` companions; refresh `architecture-diagrams.md` sequence diagram to show Web → API split (optional diagram addition — logical flows unchanged).

---

### 4.6 sprint-status.yaml (after approval)

```yaml
  1-1-bootstrap-project-from-supabase-starter-template: done
  1-1b-nestjs-api-and-docker-compose-scaffold: ready-for-dev  # NEW
  1-2-profiles-schema-and-bootstrap-admin-seed: backlog
```

---

## Section 5: Implementation Handoff

### Scope classification: **Moderate**

Backlog reorganization + one new story + multi-file epic amendments. No PRD or MVP scope change.

### Handoff plan

| Role / skill | Responsibility |
|--------------|----------------|
| **User (TNT)** | Approve this proposal |
| **`/bmad-create-story`** | Generate `1-1b-nestjs-api-and-docker-compose-scaffold.md` with full dev notes |
| **`/bmad-dev-story`** | Implement 1.1b, then 1.2, 1.3 |
| **`/bmad-spec`** | Sync SPEC architecture companion (parallel) |
| **Manual / agent** | Patch epic markdown files + `1-requirements-inventory.md` per Section 4 |

### Success criteria

- [ ] `api/` boots; `docker compose --profile local up` healthy
- [ ] Web `package.json` has no drizzle deps
- [ ] `.env.example` reflects split env model
- [ ] sprint-status.yaml lists 1.1b
- [ ] Epic 1–5 stories no longer reference `lib/domain/` or monolith Server Actions for mutations
- [ ] Story 1.1 marked `done`

### Deferred (no action in this change)

- Production API hosting (spine Deferred)
- E2E Playwright stack (user deferred)
- Shared `packages/` types between web and api

---

## Approval

**Approved by TNT on 2026-07-02.** Implementation applied: sprint-status.yaml, epic files, requirements inventory.
