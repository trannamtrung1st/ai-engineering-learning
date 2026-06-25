# Production UI Quality Bar

## Purpose

Define the minimum bar for We Event frontend work produced by the AI harness. The UI must be a **shippable product surface**—not a demo shell, wireframe placeholder, or unstyled scaffold.

Harness agents must read this document before any FrontendAgent implementation session.

## Product bar

Acceptable:
- Role-aware routes with shared app shell, semantic tokens, and live `/api/v1` data.
- Domain status communicated with badges, helper text, and accessible labels.
- Loading skeletons, empty states with next actions, and inline error recovery.

Not acceptable (hard fail):
- Static forms or buttons without real API integration.
- Hardcoded fixture arrays (`const events = [...]`) in page components.
- Demo copy (`Annual summit`, `demo-event`, lorem ipsum).
- Single monolithic "workspace" page dumping all flows.
- Unstyled HTML forms or inline layout styles.
- Color-only status indicators without text or icons.
- Rendering 100+ list rows without pagination controls.
- Fetching all pages in a loop to assemble a full client-side dataset.

## Required stack usage

| Concern | Reference |
|---|---|
| Semantic tokens | `04-design-tokens.md` — CSS variables in `globals.css` |
| App shell | `06-app-layout-components.md` — header, nav, role guards |
| Shared primitives | `05-common-ui-components.md` — Radix-based, accessible |
| Domain components | `07-event-specific-components.md` — capacity, waitlist, status |
| UI states | `12-ui-states.md` — loading, empty, error, domain badges |
| Accessibility | `13-accessibility-basics.md` — keyboard, focus, live regions |

Stack: Next.js App Router, React + TypeScript, Tailwind CSS, Radix UI (or equivalent), TanStack Query, React Hook Form + Zod.

## Page coverage (incremental by slice)

Implement routes from `09-page-list.md` per backlog slice—not all at once.

MVP minimum before convergence:
- Participant: event browse, event detail, registration status, check-in, feedback.
- Organizer Admin: event list, create/edit, operations dashboard, check-in console.
- Shared: app shell, access denied, not found, error recovery.

## Data contract

- All list and detail views fetch from `/api/v1`; backend remains authoritative for domain states.
- Listing pages must use paginated API requests (`page`/`pageSize`); see `05-api-design.md` §3.
- Fetching all pages in a loop to build a client-side list is a harness hard-fail.
- Use TanStack Query (or equivalent) for server state; no module-level mock stores in pages.
- Optimistic updates only for reversible operations with rollback UI.

## Visual polish

- 8px grid spacing; consistent typography hierarchy (page title → section → helper).
- Domain status colors from semantic tokens (`color.status.*`).
- Loading: skeleton placeholders that preserve layout (not spinner-only pages).
- Empty states: explain why empty and offer one clear next action.
- Primary CTA once per section; destructive actions require confirmation.

## Anti-patterns (harness hard fail)

| Pattern | Why it fails |
|---|---|
| `lorem ipsum` | Placeholder content |
| `mockEvents` / `const events = [` | Hardcoded data bypassing API |
| Missing `AppShell` / layout on routes | No product structure |
| Missing focus-visible styles | Accessibility regression |
| `We Event MVP` as page title only | Demo labeling without real UX |

## Slice alignment

Frontend work belongs in these backlog slices (see `ai-harness/whole-app-backlog.json`):
1. `web-design-system-shell` — tokens, layout, primitives first.
2. `web-participant-journeys` — participant flows.
3. `web-organizer-journeys` — organizer flows.

Do not implement organizer dashboards in the same session as design-system bootstrap.

## Traceability

- UX principles: `01-design-overview.md`
- User flows: `10-user-flows.md`
- Harness enforcement: `ai-harness/workflows/ralph-loop.json` completion criteria
- Review: `ai-harness/workflows/human-review-checklist.md`
