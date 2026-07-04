# Attendly — UI/UX Documentation

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Locale:** Vietnamese (`vi-VN`) user-facing copy; technical identifiers in English  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)

## 1. Overview

This folder holds the UI/UX specification for Attendly MVP. It defines the visual language (Neobrutalism), the design-system modules, reusable and domain-specific components, form/validation behavior, and the canonical page inventory. Together these let engineers and designers implement the product without guessing.

Attendly's UI focuses on **operational clarity** during time-sensitive attendance windows for students and lecturers, and **governance confidence** for admins and auditors. See [01-design-overview.md](./01-design-overview.md) for the narrative UX intent.

## 2. Precedence chain

When guidance appears in more than one place, resolve conflicts top-down:

1. **[DESIGN.md](./DESIGN.md)** — authoritative visual decisions and surface-to-token mapping.
2. **[design-system/](./design-system/)** — per-component and foundation module specs.
3. **[04-design-tokens.md](./04-design-tokens.md)** — token-to-CSS-variable mapping (§0 mapping table).
4. **[01-design-overview.md](./01-design-overview.md)** — narrative guidance.
5. Harness visual guidance — only when the sources above are silent.

This chain matches [03-design-system-basics.md](./03-design-system-basics.md) §2 and applies to every document in this folder.

## 3. Document index

| Document | Purpose |
| --- | --- |
| [DESIGN.md](./DESIGN.md) | Authoritative visual spec index, surface map, and token posture |
| [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md) | Production-readiness quality gates and acceptability rubric |
| [01-design-overview.md](./01-design-overview.md) | UX intent, surfaces, and core patterns |
| [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) | Foundational UX principles |
| [02-ui-framework-tech-stack.md](./02-ui-framework-tech-stack.md) | Frontend stack and UI architecture constraints |
| [03-design-system-basics.md](./03-design-system-basics.md) | Design-system base rules and precedence chain |
| [04-design-tokens.md](./04-design-tokens.md) | Token-to-CSS-variable mapping |
| [05-common-ui-components.md](./05-common-ui-components.md) | Reusable components, including `TableToolbar` |
| [06-app-layout-components.md](./06-app-layout-components.md) | App shells, headers, and layout components |
| [07-domain-specific-components.md](./07-domain-specific-components.md) | Attendance-specific components (QR, roster, check-in result, correction) |
| [08-forms-validation-ux.md](./08-forms-validation-ux.md) | Form specs, validation timing, and error-code mapping |
| [09-page-list.md](./09-page-list.md) | Canonical page/route inventory and listing matrix |
| [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) | Per-route search/filter/sort/pagination matrix (derived from [09-page-list.md](./09-page-list.md)) |

> Documents `04`, `06`, and `14` are authored in adjacent generation steps; links resolve as the specification set completes.

## 4. Design system modules

The design system lives in [design-system/](./design-system/). Foundation and component modules are indexed authoritatively in [DESIGN.md](./DESIGN.md) §8.

| Group | Modules |
| --- | --- |
| Foundation | [colors.md](./design-system/colors.md), [typography.md](./design-system/typography.md), [layout.md](./design-system/layout.md), [radius.md](./design-system/radius.md), [shadows.md](./design-system/shadows.md), [borders.md](./design-system/borders.md) |
| Core components | [buttons.md](./design-system/buttons.md), [button-group.md](./design-system/button-group.md), [cards.md](./design-system/cards.md), [inputs.md](./design-system/inputs.md), [alerts.md](./design-system/alerts.md), [badges.md](./design-system/badges.md), [avatars.md](./design-system/avatars.md), [lists.md](./design-system/lists.md), [icon-shapes.md](./design-system/icon-shapes.md) |
| Complex components | [accordion.md](./design-system/accordion.md), [dropdown.md](./design-system/dropdown.md), [modals.md](./design-system/modals.md), [tabs.md](./design-system/tabs.md), [tables.md](./design-system/tables.md), [pagination.md](./design-system/pagination.md), [sidebars.md](./design-system/sidebars.md), [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md), [tooltips-popovers.md](./design-system/tooltips-popovers.md), [content.md](./design-system/content.md) |

## 5. Visual language at a glance

Attendly uses a **Neobrutalism** style ([DESIGN.md](./DESIGN.md) §1):

- Hard offset shadows with no blur.
- `2px`–`3px` black borders — structural, not decorative.
- Default `0px` corner radius, except explicit pill/circle patterns (badges, avatars, `QrCountdownRing`).
- Strong contrast and bold, high-legibility typography for fast scanning in classroom contexts.
- Semantic color roles: success (`Present`), warning (`Late`), danger (`Absent`/rejections), neutral/brand (informational).

## 6. Primary surfaces

| Surface | Primary actor | Docs |
| --- | --- | --- |
| Student check-in and history | Student | [07-domain-specific-components.md](./07-domain-specific-components.md) §3, [09-page-list.md](./09-page-list.md) §2–3 |
| Lecturer session control & roster | Lecturer | [07-domain-specific-components.md](./07-domain-specific-components.md) §2, §4, [09-page-list.md](./09-page-list.md) §4 |
| Admin setup & policy | AcademicAdmin / DepartmentAdmin | [08-forms-validation-ux.md](./08-forms-validation-ux.md) §4, [09-page-list.md](./09-page-list.md) §5 |
| Reporting, export & audit | Lecturer / Admin / Auditor | [09-page-list.md](./09-page-list.md) §6–7 |

## 7. Related specifications

- Business requirements: [../brds/00-project-overview.md](../brds/00-project-overview.md), [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md), [../brds/04-business-rules.md](../brds/04-business-rules.md)
- Technical: [../technical/01-roles-permissions.md](../technical/01-roles-permissions.md), [../technical/05-api-design.md](../technical/05-api-design.md), [../technical/08-validation-rules.md](../technical/08-validation-rules.md)
- Product metadata: [../product-meta.json](../product-meta.json)

## 8. Contributor guidance

- Follow the precedence chain in §2 for any visual or behavioral decision.
- Reuse components from [05-common-ui-components.md](./05-common-ui-components.md) and [07-domain-specific-components.md](./07-domain-specific-components.md) before introducing new ones.
- Keep student-facing copy concise Vietnamese; align error text with backend reason codes ([08-forms-validation-ux.md](./08-forms-validation-ux.md) §5).
- Stay within MVP scope; place enhancements under each document's "Future consideration" section.
