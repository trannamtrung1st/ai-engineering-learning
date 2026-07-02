# Attendly — UI Framework and Tech Stack

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [../technical/12-backend-frontend-tech-stack.md](../technical/12-backend-frontend-tech-stack.md) · [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) · [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md)

## 1. Purpose

Define the frontend implementation stack and UI architecture constraints for Attendly MVP.

## 2. Recommended frontend baseline

### 2.1 Framework and runtime

| Layer | Selection | Rationale |
| --- | --- | --- |
| UI framework | React + TypeScript | Strong ecosystem and shared typing with backend contracts |
| Build/runtime | Vite | Fast iteration for design-system-heavy UI |
| Routing | React Router | Clear role-based route segmentation |
| Server-state | TanStack Query | Reliable request lifecycle, retries, and cache controls |
| Forms | React Hook Form + Zod | Predictable validation and error handling |

### 2.2 Optional framework path

`Next.js` is acceptable when team constraints justify SSR/hybrid rendering, but MVP should keep student check-in latency and flow simplicity as top priority.

## 3. UI architecture requirements

### 3.1 Structural requirements

- `FR-STACK-01`: Shared app shell components for staff routes.
- `FR-STACK-02`: Mobile-focused minimal shell for student check-in flows.
- `FR-STACK-03`: Design tokens exposed via CSS variables and consumed by component primitives.
- `FR-STACK-04`: Role-aware route guards and view-level permission checks.

### 3.2 Quality requirements

- `NFR-STACK-01`: Avoid full-page reloads for realtime roster updates.
- `NFR-STACK-02`: Preserve loading, error, and stale-data states in listing pages.
- `NFR-STACK-03`: Ensure keyboard and focus visibility standards are built into primitives.

## 4. Styling strategy

### 4.1 Token-driven styling

- `BR-STACK-01`: Use semantic tokens from `04-design-tokens.md`, not hardcoded visual values.
- `BR-STACK-02`: Respect Neobrutalism constraints from `DESIGN.md`.
- `BR-STACK-03`: Component-level state styles must align with `design-system/*` modules.

### 4.2 Component architecture

- Base primitives: button, input, badge, alert, card, table.
- Composite components: `TableToolbar`, roster panel, session control panel, permission banner.
- Route compositions: student check-in, lecturer session, admin listing/reporting, audit review.

## 5. Data and interaction model

### 5.1 API alignment

- Standardized query params for listing routes (`search`, filters, sort, pagination).
- Stable error-code mapping for user-facing feedback.
- Mutation responses drive toast/alert and local cache updates.

### 5.2 Realtime handling

- Prefer WebSocket or SSE for open-session roster updates.
- Graceful fallback to controlled polling for non-realtime contexts.
- Keep user context (scroll, selected row) stable while updates arrive.

## 6. Testing and verification for UI stack

| ID | Scope | Requirement |
| --- | --- | --- |
| `AC-STACK-01` | Component tests | Core primitives render all required states |
| `AC-STACK-02` | Route tests | Key routes enforce role-safe behaviors |
| `AC-STACK-03` | E2E tests | Student check-in and lecturer open/close workflows pass |
| `AC-STACK-04` | Accessibility checks | Focus, labels, and contrast standards pass |
| `AC-STACK-05` | Responsive checks | Mobile student flow and desktop staff views remain usable |

## 7. Cross-links to requirements

| UI stack decision | Requirement linkage |
| --- | --- |
| Mobile-first check-in implementation | `FR-16`, `NFR-14` |
| Realtime lecturer roster model | `FR-19`, `NFR-01` |
| Route and action permission gating | `FR-27`, `FR-32`, `BR-19` |
| Error-code-based UX messaging | `FR-22`, `BR-23`, `AC-18` |

## 8. Future consideration

- Monorepo UI package split for multi-app scaling.
- Storybook-driven visual regression workflow.
- Advanced performance profiling for large report tables.
