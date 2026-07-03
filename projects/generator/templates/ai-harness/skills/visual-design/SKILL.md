---
name: visual-design
description: Generic design-system craft for {{PRODUCT_NAME}} UI — read design-system modules, apply style profile tokens, and enforce screenshot review for implementer and browser tester agents.
---

# Visual Design Craft ({{PRODUCT_NAME}} Harness)

Harness skill for **{{DESIGN_STYLE_NAME}}** visual implementation. Product specs live in `docs/ui-ux/`; this skill governs how agents read and apply them.

**Style profile:** borders ({{BORDER_STYLE}}), radius ({{RADIUS_DEFAULT}}), elevation ({{SHADOW_STYLE}}), primary ({{PRIMARY_COLOR}}), fonts ({{HEADING_FONT}} / {{BODY_FONT}}).

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

Apply the **{{DESIGN_STYLE_NAME}}** profile consistently:

- **Borders:** per `borders.md` and DESIGN.md style profile ({{BORDER_STYLE}})
- **Radius:** per `radius.md` (default {{RADIUS_DEFAULT}})
- **Elevation:** per `shadows.md` ({{SHADOW_STYLE}})
- **Typography:** headings use {{HEADING_FONT}}; body uses {{BODY_FONT}}
- **Primary CTA:** uses primary token ({{PRIMARY_COLOR}}) with documented contrast pair
- **Tokens:** agnostic names mapped in `tokens.css` — not literal framework defaults

---

## Anti-template bar

The UI must feel **intentional** — not a generic gray SaaS template. Craft failures:

- Default framework styling without token alignment
- Identical styling for success, warning, empty, and error states
- Raw hex in component CSS Modules
- Missing hover/focus/disabled states on interactive surfaces
- Listing routes without `TableToolbar` per docs
- No visual differentiation between page sections or content hierarchy
- Hero/landing areas that are blank, empty shells, or simple "Hello" placeholders

Every primary flow must contain at least one intentional visual moment that signals a real product: a styled stat card on a dashboard, an outcome accent on a status badge, a recovery affordance with clear messaging, or a meaningful empty state with a call to action. Secondary flows may be simpler, but none may feel like an unstyled framework default.

---

## Copy hygiene (non-negotiable)

User-visible text — headings, labels, table column headers, button copy, toast messages, placeholder text, and empty-state descriptions — must use human-readable domain language. Never expose internal system identifiers in the UI.

**Forbidden in user-facing copy:**

- Acceptance / requirement codes: `AC-01`, `FR-03`, `NFR-18`, `BR-07`
- Schema or database field names: `item_id`, `created_at`, `slice_id`, `user_uuid`
- Internal slice or agent names: `web-auth-session-pages`, `domain-package`
- JSON keys or enum literals used verbatim: `status: "PENDING_REVIEW"`, `role: "ROLE_A"`
- Error codes without human context: `ERR_403`, `ECONNREFUSED`

**Use instead:** domain nouns and verbs from `docs/brds/` and `docs/ui-ux/`. Map status enums to readable labels in the presentation layer. Expose descriptive error messages, not raw codes.

The tester must flag any visible technical identifier as a **P1** defect — it means internal state leaked into the UI.

---

## Navigation structure (required on every screen)

Every authenticated page must be discoverable and escapable via a persistent navigation surface. Implement all four rules before `SLICE_DONE`:

1. **Persistent nav surface** — every authenticated route is reachable from a sidebar, top navigation bar, or contextual breadcrumb chain. No page is a dead end reachable only via the browser back button.
2. **Home link always visible** — the navigation surface must include a home/dashboard link on every authenticated page. The **app logo in the nav header or sidebar is the primary home shortcut** — it must be a clickable link to the role's default hub, not decorative-only. An explicit "Home" nav item or breadcrumb first segment also satisfies this rule.
3. **Orientation on deep pages** — any page more than one level from home must display a breadcrumb trail or a section heading that makes clear where the user is. The first breadcrumb segment must link back to home.
4. **No dead-end pages** — modal confirmations, detail views, and outcome pages must each provide a clear next action or an explicit path back (close, cancel, back link, or breadcrumb).

Apply `sidebars.md` for the nav surface structure, including the required home item at the top of the list.

---

## Entry flows (landing page and login)

### Home / landing page

The authenticated root (`/` after login) must render a meaningful, role-appropriate hub — not an empty shell, a redirect loop, or a "coming soon" placeholder. Minimum content:

- A clear page heading that names the space the user is in (use domain language, not the role's technical slug).
- Primary actions or quick-access links for the most common tasks for this role.
- At least one live data surface: a summary count, a recent-items list, or a status overview that updates from the backend.

The home page is the navigation anchor for the entire role experience. It must be reachable from every other page.

### Login page

The login page must be **role-agnostic**:

- Heading, subheading, and form copy must not mention any role name or role-specific functionality.
- Do not conditionally render different copy or form fields per role on the login screen.
- After successful authentication, the app reads the authenticated user's role from the session/token and **redirects programmatically** to that role's configured default route, as defined in `docs/technical/01-roles-permissions.md`.
- If multiple roles share the same default route, a single redirect is sufficient. If roles differ, the redirect logic must branch per role — never hard-code a single path for all roles.

---

## RBAC visibility (strict — non-negotiable)

Navigation items and page links that a role is not permitted to access must be **absent from the rendered output** — not hidden with CSS, not rendered as disabled anchor tags, not conditionally opacity-zeroed. The server-side session determines the role; the client renders only what that role is allowed to see.

### Forbidden nav items

- Check the role's permission set against `docs/technical/01-roles-permissions.md` before rendering each nav item.
- Do not render a nav item — not even as a disabled state — if the current role lacks the required permission.
- Apply this at both the sidebar level and any inline links within page content (breadcrumbs, "Go to…" links, related-resource links).

### Forbidden routes (access-denied page)

If a user navigates directly to a route their role cannot access (e.g. by typing a URL), the app must:

1. **Render a styled access-denied page** using the product's outcome/alert surface (see `alerts.md`). Not a crash, not a blank screen, not a redirect back to login.
2. Display a clear, human-readable message explaining the user does not have access (no technical error codes).
3. Include a prominent link back to the user's home page so they can recover without the browser back button.

The access-denied state is a first-class UI surface — style it with the same care as any other page.

---

## Tester FAIL criteria

Flag as UX/visual defect when screenshots show:

- Token drift (wrong primary, radius, or elevation vs DESIGN.md)
- Missing borders/shadows where design-system modules require them
- Wrong fonts vs token mapping
- Touch targets below 44×44 px on primary mobile actions
- Outcome badges/alerts not matching DESIGN.md domain bridge
- Technical identifiers (IDs, codes, field names) visible in user-facing copy
- Missing navigation surface or no home link on any authenticated page
- Login page with role-specific copy or heading
- Forbidden nav item visible for the wrong role
- Forbidden route renders a crash, blank screen, or login redirect instead of access-denied page

Cross-reference [ui-ux-testing](../ui-ux-testing/SKILL.md) and [ui-visual-verification.md](../../docs/ui-visual-verification.md).

---

## Ground it in the product

Read `docs/ui-ux/01-ui-ux-foundation.md` for personas, locales, and canonical states. Design for real users under real constraints — not a marketing landing page.
