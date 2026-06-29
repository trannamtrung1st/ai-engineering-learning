# We Check — UI/UX Documentation

Design and interaction specifications for **We Check**, the digital attendance and session check-in system for educational workshops and classes (HESD program). All documents target MVP delivery for cohorts of **100–150** participants per session, locale **vi-VN**.

**Product context:** [Project overview](../brds/00-project-overview.md) · [Stakeholders and scope](../brds/01-stakeholders-scope.md) · [Initial idea](../initial-idea.md)

**Technical companion:** [Frontend tech stack](../technical/12-backend-frontend-tech-stack.md) · [Roles and permissions](../technical/01-roles-permissions.md)

---

## 1. Document Index

Read in numbered order for first-time onboarding. Cross-link freely after foundation sections.

| # | Document | Purpose |
| --- | --- | --- |
| 00 | [Production UI quality bar](./00-production-ui-quality-bar.md) | Non-negotiable visual and interaction standards |
| 01 | [Design overview](./01-design-overview.md) | Product UX goals, principles, and information architecture |
| 01 | [UI/UX foundation](./01-ui-ux-foundation.md) | Terminology, state labels, permission flows, localization |
| 02 | [UI framework and tech stack](./02-ui-framework-tech-stack.md) | React, Tailwind, Radix, routing, and tooling |
| 03 | [Design system basics](./03-design-system-basics.md) | Typography, spacing, elevation, iconography |
| 04 | [Design tokens](./04-design-tokens.md) | CSS variables, color roles, semantic tokens |
| 05 | [Common UI components](./05-common-ui-components.md) | Shared primitives and compositions |
| 06 | [App layout components](./06-app-layout-components.md) | Role shells, navigation, page scaffolding |
| 07 | [Event-specific components](./07-event-specific-components.md) | Domain widgets: QR, sessions, attendance, reports |
| 08 | [Forms and validation UX](./08-forms-validation-ux.md) | Form patterns, validation timing, error presentation |
| 09 | [Page list](./09-page-list.md) | Complete route inventory with roles and traceability |
| 10 | [User flows](./10-user-flows.md) | End-to-end journeys by actor *(downstream)* |
| 11 | [Wireframes](./11-wireframes.md) | Low-fidelity screen layouts *(downstream)* |
| 12 | [UI states](./12-ui-states.md) | Loading, empty, error, and edge states *(downstream)* |
| 13 | [Accessibility basics](./13-accessibility-basics.md) | WCAG checklist and test plan *(downstream)* |
| 14 | [Listing pages, search, filter, sort](./14-listing-pages-search-filter-sort.md) | Data table UX patterns *(downstream)* |

---

## 2. Reading Paths by Role

### 2.1 Frontend engineer

1. [02-ui-framework-tech-stack.md](./02-ui-framework-tech-stack.md) — stack and folder structure
2. [04-design-tokens.md](./04-design-tokens.md) + [05-common-ui-components.md](./05-common-ui-components.md) — build primitives first
3. [06-app-layout-components.md](./06-app-layout-components.md) — wire routes to layouts
4. [09-page-list.md](./09-page-list.md) — implement pages in priority order
5. [07-event-specific-components.md](./07-event-specific-components.md) + [08-forms-validation-ux.md](./08-forms-validation-ux.md) — feature components and forms

### 2.2 Designer

1. [01-design-overview.md](./01-design-overview.md) + [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md)
2. [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) — labels and states
3. [09-page-list.md](./09-page-list.md) — screen inventory
4. [11-wireframes.md](./11-wireframes.md) *(when available)*

### 2.3 QA / test author

1. [09-page-list.md](./09-page-list.md) — coverage matrix
2. [08-forms-validation-ux.md](./08-forms-validation-ux.md) — validation cases
3. [Acceptance criteria](../brds/08-acceptance-mvp-future.md) — AC-xx scenarios
4. [12-ui-states.md](./12-ui-states.md) *(when available)*

---

## 3. MVP Scope Summary

In-scope UI capabilities align with [01-stakeholders-scope.md](../brds/01-stakeholders-scope.md) §2.1:

| Actor | Primary screens |
| --- | --- |
| `Student` | Mobile check-in (QR + GPS), attendance history |
| `Instructor` | Session management, QR display, live monitor, roster edit, class reports |
| `TrainingOfficeAdmin` | User provisioning, roster import, institution reports, CSV export, policy config |
| `ITOperations` | No in-app MVP UI |

Out of scope: native apps, facial recognition, tuition, exam scheduling, SSO (deferred).

---

## 4. Requirement Traceability

UI/UX docs reference business requirements by ID:

| Prefix | Source |
| --- | --- |
| `FR-xx` | [Functional requirements](../brds/03-functional-requirements.md) |
| `BR-xx` | [Business rules](../brds/04-business-rules.md) |
| `AC-xx` | [Acceptance criteria](../brds/08-acceptance-mvp-future.md) |
| `NFR-xx` | [Non-functional requirements](../brds/07-non-functional-risk.md) |

Traceability matrices appear in [06-app-layout-components.md](./06-app-layout-components.md) §13, [07-event-specific-components.md](./07-event-specific-components.md) §10, [08-forms-validation-ux.md](./08-forms-validation-ux.md) §8, and [09-page-list.md](./09-page-list.md) §10.

---

## 5. Component Hierarchy

```
apps/web/src/components/
├── ui/           ← primitives (05-common-ui-components)
├── shared/       ← compositions (forms, tables, feedback)
├── layout/       ← shells (06-app-layout-components)
└── domain/       ← attendance domain (07-event-specific-components)
```

Pages under `apps/web/src/routes/` compose layout + domain + shared only.

---

## 6. Documentation Phases

These documents are organized in **Phase 3 (UI/UX)** of the spec documentation:

| Step | Outputs |
| --- | --- |
| `uiux-foundation-system` | 00–06 |
| `uiux-components-pages` | 07–09, this README |
| `uiux-flows-wireframes-states` | 10–14 |
| `uiux-consistency-gate` | AC cross-reference validation |

---

## 7. Related BRD Documents

| Topic | Document |
| --- | --- |
| Workflows | [02-business-workflow.md](../brds/02-business-workflow.md) |
| State machines | [05-state-machine.md](../brds/05-state-machine.md) |
| Domain model | [06-domain-model.md](../brds/06-domain-model.md) |
| MVP vs future | [08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md) |

---

## 8. Future Consideration

- Storybook catalog linked from this README.
- Figma file URL once design artifacts exist.
- Dark mode token set (MVP is light mode only).
- Component visual regression baseline screenshots.
