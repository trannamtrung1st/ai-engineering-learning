---
name: visual-design
description: Generic design-system craft for Attendly UI — read design-system modules, apply style profile tokens, and enforce screenshot review for implementer and browser tester agents.
---

# Visual Design Craft (Attendly Harness)

Harness skill for **Neobrutalism** visual implementation. Product specs live in `docs/ui-ux/`; this skill governs how agents read and apply them.

**Style profile:** borders (2px solid #000000), radius (0px), elevation (hard offset shadows with no blur (shadow-xs through shadow-2xl)), primary (#FFDB33), fonts (Archivo Black, sans-serif / Space Grotesk, sans-serif).

## Precedence (non-negotiable)

| Topic | Authoritative doc |
| --- | --- |
| Scope, module index, domain bridge | [docs/ui-ux/DESIGN.md](../../../docs/ui-ux/DESIGN.md) |
| Component visual specs | [docs/ui-ux/design-system/](../../../docs/ui-ux/design-system/) |
| CSS variable mapping | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) |
| Quality gate | [docs/ui-ux/00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) |
| Component contracts | [docs/ui-ux/05-common-ui-components.md](../../../docs/ui-ux/05-common-ui-components.md), [06-app-layout-components.md](../../../docs/ui-ux/06-app-layout-components.md) |
| Page inventory, home hubs, nav entry points | [docs/ui-ux/09-page-list.md](../../../docs/ui-ux/09-page-list.md) |
| User flows | [docs/ui-ux/10-user-flows.md](../../../docs/ui-ux/10-user-flows.md) |
| Listing page matrix | [docs/ui-ux/14-listing-pages-search-filter-sort.md](../../../docs/ui-ux/14-listing-pages-search-filter-sort.md) |

Never bypass tokens, accessibility, or business rules for aesthetics.

---

## Before writing code

Read every module that applies to the screen:

| Screen type | Minimum modules |
| --- | --- |
| Any UI | `layout.md`, `typography.md`, `colors.md`, `shadows.md`, `radius.md`, `borders.md` |
| Forms / auth | + `inputs.md`, `buttons.md`, `cards.md` |
| Listing / data views | + `tables.md`, `tabs.md`, `sidebars.md` |
| Modals / dialogs | + `modals.md` |
| Outcome states | + `alerts.md`, `badges.md` |

Do NOT write UI code until relevant modules are loaded.

---

## Style signatures (required)

Apply the **Neobrutalism** profile consistently:

- **Borders:** per `borders.md` and DESIGN.md style profile (2px solid #000000)
- **Radius:** per `radius.md` (default 0px)
- **Elevation:** per `shadows.md` (hard offset shadows with no blur (shadow-xs through shadow-2xl))
- **Typography:** headings use Archivo Black, sans-serif; body uses Space Grotesk, sans-serif
- **Primary CTA:** uses primary token (#FFDB33) with documented contrast pair
- **Tokens:** agnostic names mapped in `tokens.css` — not literal framework defaults

---

## Anti-template bar

The UI must feel **intentional** — Neobrutalism is a deliberate visual language, not a generic gray SaaS template. Craft failures:

- Default framework styling without token alignment
- Identical styling for success, warning, empty, and error states
- Raw hex in component CSS Modules
- Missing hover/focus/disabled states on interactive surfaces
- Listing routes without `TableToolbar` per docs
- Missing 2px solid `#000000` border or hard-offset shadow on any interactive card or surface — this is a Neobrutalism failure, not a cosmetic detail
- Check-in flow or home pages that are blank shells with only a "Điểm danh thông minh" heading and no live data surface

Every primary flow (check-in, session open, live roster, report listing) must contain at least one intentional Neobrutalism visual moment: a status badge with a bold border accent, a hard-shadow stat card, a recovery affordance with `#FFDB33` primary CTA, or a meaningful empty state with Arquivo Black heading. Secondary flows may be simpler, but none may feel like an unstyled framework default.

---

## Copy hygiene (non-negotiable)

All vi-VN visible text — headings, labels, table column headers, button copy, toast messages, placeholder text, and empty-state descriptions — must use human-readable domain language. Never expose internal system identifiers in the UI.

**Forbidden in user-facing copy:**

- Requirement codes: `AC-01`, `FR-15`, `NFR-09`, `BR-19`
- Schema or database field names: `student_id`, `session_uuid`, `created_at`, `class_section_id`
- Raw status enum literals: `PENDING_VERIFICATION`, `ABSENT`, `PRESENT` — map these to readable Vietnamese labels
- Internal slice or agent names
- Raw error codes without human context: `ERR_403`, `OutOfScope`, `Unauthenticated`

**Required label mapping (examples):**

| Enum / code | User-facing Vietnamese label |
| --- | --- |
| `PRESENT` | Có mặt |
| `ABSENT` | Vắng mặt |
| `LATE` | Đi muộn |
| `PENDING_VERIFICATION` | Đang xác minh |
| `403` / `Forbidden` | Bạn không có quyền truy cập tính năng này |

Use domain nouns and verbs from `docs/brds/` and `docs/ui-ux/`. The tester must flag any visible technical identifier as a **P1** defect.

---

## Navigation structure (required on every screen)

Every authenticated page must be discoverable and escapable via a persistent navigation surface. Implement all four rules before `SLICE_DONE`:

1. **Persistent nav surface** — every authenticated route must be reached from a shell layout: `StaffLayout` (`SidebarNav`) for Lecturer/DepartmentAdmin/AcademicAdmin/ITAdmin/SystemAuditor, `AdminLayout` for academic admin setup pages, `StudentLayout` mobile shell for Student flows. No page should be reachable only via browser back button.
2. **Home link always visible** — `SidebarNav` must include the role's primary dashboard link at the top of the list (e.g. "Phiên học" → `/lecturer/sessions` for Lecturer, "Thiết lập học kỳ" → `/admin/terms` for AcademicAdmin). `StudentLayout` must include a "Trang chủ" link or linked product logo pointing to `/check-in`.
3. **Orientation on deep pages** — any route deeper than one level (e.g. `/lecturer/sessions/{id}`, `/admin/terms/{id}`, `/me/history`) must render a breadcrumb row via `TopContextHeader` per `docs/ui-ux/06-app-layout-components.md`. The first breadcrumb segment must link back to the section home.
4. **No dead-end pages** — session detail views, form pages, and outcome confirmations must each provide a clear next action or path back (close button, breadcrumb, or sidebar home link).

Apply `docs/ui-ux/design-system/sidebars.md` for the nav surface structure, including the required home item at the top of the list.

---

## Entry flows (login and home)

### Home / landing page

The authenticated root must render a meaningful, role-appropriate hub — not an empty shell, a redirect to `/showcase`, or a "coming soon" placeholder. Minimum content per role:

- **Student:** `/check-in` hub with QR scan prompt and recent attendance summary
- **Lecturer:** `/lecturer/sessions` — list of today's and upcoming scheduled sessions
- **AcademicAdmin:** `/admin/terms` — active term overview with quick-access to class sections and policies
- **ITAdmin / SystemAuditor:** `/audit/logs` — recent audit log entries with status indicators

The home page is the navigation anchor for each role's experience. It must be reachable from every other page.

### Login page

The login page (`/login`, `PG-01`) must be **role-agnostic**:

- Heading must be a single generic label such as "Đăng nhập" — never "Đăng nhập Giáo viên", "Đăng nhập Admin", or any role-specific variant.
- Do not conditionally render different copy, sub-headings, or form fields per role on the login screen.
- After successful authentication, read the resolved role from the JWT / session and redirect to that role's configured default route:

| Role | Default route |
| --- | --- |
| Student | `/check-in` |
| Lecturer | `/lecturer/sessions` |
| DepartmentAdmin | `/lecturer/sessions` |
| AcademicAdmin | `/admin/terms` |
| ITAdmin | `/audit/logs` |
| SystemAuditor | `/audit/logs` |

When `returnUrl` is present in the query string, prefer it over the default. When absent, use the table above — never hard-code `/check-in` as the fallback for all roles.

---

## RBAC visibility (strict — non-negotiable)

Navigation items and page links that a role is not permitted to access must be **absent from the rendered output** — not hidden with CSS, not rendered as disabled anchor tags, not opacity-zeroed. `role-guard.ts` functions are the authority for render decisions; check them before rendering each nav item.

### Forbidden nav items

- `StaffLayout SidebarNav` already filters by `role-guard.ts` — this must remain the pattern for all nav items. Do not render a nav item — not even as a disabled state — if `role-guard.ts` returns false for the current role.
- Apply this to inline links within page content (breadcrumb "Go to…" links, related-resource links, cross-role action buttons).

### Forbidden routes (access-denied surface)

If an authenticated user navigates directly to a route their role cannot access (e.g. Student → `/lecturer/sessions`, ITAdmin → `/admin/terms`), the app must:

1. **Render a styled access-denied surface** using `FeedbackAlert variant="danger"` (see `alerts.md`). Not a crash, not a blank screen, not a redirect back to `/login` — the user is already authenticated.
2. Display a human-readable vi-VN message explaining the restriction. Example: "Bạn không có quyền truy cập trang này."
3. Include a prominent "Về trang chủ" link back to the current role's home page (use the default route table above).

The access-denied state is a first-class UI surface. Apply Neobrutalism styling: 2px border, hard shadow, `#FFDB33` accent on the recovery CTA button.

---

## Tester FAIL criteria

Flag as UX/visual defect when screenshots show:

- Token drift (wrong primary `#FFDB33`, radius `0px`, or hard-offset elevation vs DESIGN.md)
- Missing 2px solid black border or hard-shadow on interactive surfaces
- Wrong fonts (Archivo Black / Space Grotesk) vs token mapping
- Touch targets below 44×44 px on primary mobile actions (check-in submit, session open/close)
- Outcome badges/alerts not matching DESIGN.md domain bridge
- Technical identifiers (`student_id`, `session_uuid`, `AC-01`, raw enum literals) visible in vi-VN user-facing copy
- Missing navigation surface or no home link on any authenticated page
- Login page with role-specific heading (e.g. "Đăng nhập Giáo viên")
- Post-login redirect landing on wrong role home (e.g. Lecturer landing on `/check-in`)
- Forbidden nav item visible for the wrong role
- Forbidden route renders blank screen, crash, or login redirect instead of styled access-denied surface
- Access-denied surface with no "Về trang chủ" link

Cross-reference [ui-ux-testing](../ui-ux-testing/SKILL.md) and [ui-visual-verification.md](../../docs/ui-visual-verification.md).

---

## Ground it in the product

Read `docs/ui-ux/01-ui-ux-foundation.md` for personas (Student, Lecturer, AcademicAdmin, ITAdmin, SystemAuditor), vi-VN locale requirements, and canonical attendance states. Design for real campus users under real constraints — not a marketing landing page.
