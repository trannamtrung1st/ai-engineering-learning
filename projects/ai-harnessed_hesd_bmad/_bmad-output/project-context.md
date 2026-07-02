---
project_name: 'ai-harnessed_hesd'
user_name: 'TNT'
date: '2026-07-02'
sections_completed: ['discovery', 'technology_stack', 'language_specific_rules', 'planning_artifacts']
existing_patterns_found: 11
source_scope: 'raw'
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- **Architecture router:** `_bmad-output/planning-artifacts/architecture/architecture-ai-harnessed_hesd-2026-07-02/index.md`
- **Agent build guide:** `.../implementation/index.md` — cold start, build order, module map.
- **Runtime stack:** Next.js 16.2.9 web + NestJS 11.1.27 API (`api/`), Supabase (Postgres + Auth + Realtime), Drizzle ORM 0.45.2 in API, TypeScript, Tailwind. Web bootstrapped via `create-next-app -e with-supabase`; API via `nest new api`. Local infra: `docker compose --profile local` (Postgres + API); integration profile for CI tests.
- BMad module config version is `6.9.0`; this is workflow metadata, not the product runtime.
- Product target is a mobile-web attendance system for HESD workshops with dynamic QR check-in, GPS validation, realtime monitoring, manual fallback, audit logs, and CSV export.
- UI design language is Neobrutalism, provided as design-system instructions and agnostic tokens rather than framework-specific classes.
- Integrated BMad skill: `.agents/skills/neobrutalism-design-system` routes agents to `docs/ui-ux/design-system/` module files before UI implementation.

## Planning Artifacts (Agent Doc Loading)

Sharded docs use **entry-point stubs** at the run-folder root (`prd.md`, `DESIGN.md`, `EXPERIENCE.md`, `ARCHITECTURE-SPINE.md`, `IMPLEMENTATION.md`, `epics.md`) that point to canonical `index.md` files inside subfolders. Load stubs only to discover paths — load section files for content.

### PRD

- **Stub:** `_bmad-output/planning-artifacts/prds/prd-ai-harnessed_hesd-2026-07-02/prd.md`
- **Canonical:** `.../prd/index.md`
- **Routing:** glossary → `prd/3-glossary.md`; features → `prd/4-features.md`; journeys → `prd/2-target-user.md`; NFRs → `prd/5-cross-cutting-nfrs.md`

### UX (DESIGN + EXPERIENCE spines)

- **Master router:** `_bmad-output/planning-artifacts/ux-designs/ux-ai-harnessed_hesd-2026-07-02/index.md`
- **Stubs:** `DESIGN.md` → `design/index.md`; `EXPERIENCE.md` → `experience/index.md`
- **Tokens:** `design/index.md` YAML frontmatter (`{colors.*}`, `{typography.*}`, `{components.*}`)
- **Routing:** IA → `experience/1-information-architecture.md`; student check-in → `experience/10-flow-uj3-trang-checkin.md`; QR Display → `experience/9-flow-uj2-minh-open-session.md`; visual components → `design/7-components.md`
- EXPERIENCE cross-references DESIGN tokens by name (`{path.to.token}`). Spines win on conflict with mocks.

### Design system (implementation layer)

- Module files: `docs/ui-ux/design-system/` — load via `.agents/skills/neobrutalism-design-system` before building UI components.

### Architecture (SPINE + IMPLEMENTATION)

- **Master router:** `_bmad-output/planning-artifacts/architecture/architecture-ai-harnessed_hesd-2026-07-02/index.md`
- **Stubs:** `ARCHITECTURE-SPINE.md` → `spine/index.md`; `IMPLEMENTATION.md` → `implementation/index.md`
- **Routing:** check-in ADs → `spine/3-ad-check-in.md`; auth/roles → `spine/4-ad-auth-security.md`; deployment/compose → `spine/6-ad-deployment.md`; ERD/source tree → `spine/9-structural-seed.md`; cold start → `implementation/2-cold-start.md`; build phases → `implementation/3-build-order.md`

### Epics & Stories

- **Stub:** `_bmad-output/planning-artifacts/epics.md`
- **Canonical:** `.../epics/epics-ai-harnessed_hesd-2026-07-02/index.md`
- **Routing:** requirements → `1-requirements-inventory.md`; epic summaries → `2-epic-list.md`; implement story → `epic-{N}-*.md`

## Critical Implementation Rules

### Language-Specific Rules

- No language-specific conventions are established yet. Agents must inspect newly added package/config files before applying TypeScript, JavaScript, Python, or backend patterns.
- Do not invent strict-mode, import/export, formatter, linter, or error-handling rules until the implementation stack is committed in the repo.
- Preserve product invariants regardless of language: QR tokens are short-lived multi-use session tokens, while one successful check-in is enforced per student per workshop session.
