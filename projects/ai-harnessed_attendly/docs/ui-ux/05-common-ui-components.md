# Attendly — Common UI Components

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [DESIGN.md](./DESIGN.md) · [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md) · [06-app-layout-components.md](./06-app-layout-components.md) · [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md)

## 1. Purpose

Define cross-route reusable components and expected behavior across student and staff interfaces.

## 2. Component catalog

| Component | Scope | Primary usage |
| --- | --- | --- |
| `AppHeader` | All staff routes | Context title, status, and key actions |
| `StatusBadge` | All routes | Session/attendance/outcome state visibility |
| `FeedbackAlert` | All routes | Success, warning, and failure messaging |
| `PrimaryActionButton` | All routes | Main task completion action |
| `TableToolbar` | Privileged and listing routes | Search/filter/sort/actions before table |
| `DataTable` | Listing/report routes | Dense tabular content |
| `ConfirmActionModal` | Mutation flows | Destructive and policy-sensitive confirmations |
| `IdentityCell` | Staff lists | Avatar + user identity block |

## 3. Shared component requirements

### 3.1 State and feedback requirements

- `FR-CMP-01`: Components support default, hover, focus, disabled states.
- `FR-CMP-02`: Async actions expose loading and failure state.
- `FR-CMP-03`: Permission-limited actions provide clear disabled/hidden behavior by role.

### 3.2 Accessibility requirements

- `NFR-CMP-01`: Focus ring is visible and consistent.
- `NFR-CMP-02`: Interactive elements have accessible labels.
- `NFR-CMP-03`: Keyboard interaction works for toolbar, table actions, and dialogs.

## 4. `TableToolbar` specification

### 4.1 Purpose and mandatory usage

`TableToolbar` is mandatory for privileged and listing routes, including admin management pages, reporting pages, and audit/evidence listings.

### 4.2 Structure

| Region | Content |
| --- | --- |
| Left | Search input and optional quick filters |
| Center | Advanced filters (dropdowns/date/status) |
| Right | Sort controls and contextual actions (`Export`, `Bulk action`) |

### 4.3 Behavior requirements

- `FR-TTB-01`: Search updates table query state and supports reset.
- `FR-TTB-02`: Filters show active-state chips and clear-all option.
- `FR-TTB-03`: Sort state is visible and reversible.
- `FR-TTB-04`: Actions are role-scoped and disabled/hidden when unauthorized.
- `FR-TTB-05`: Toolbar state syncs with route query params.

### 4.4 Route expectations

| Route type | `TableToolbar` behavior expectation |
| --- | --- |
| Lecturer listings | Fast filter by session/class with lightweight defaults |
| Admin management | Rich filters for term/course/section/policy dimensions |
| Reporting/export | Explicit scope and status filters before export |
| Audit review | Time range, actor, and action-type filters as first-class controls |

## 5. Component-level patterns

### 5.1 Status and feedback

- `StatusBadge` uses semantic status mapping (`Present`, `Late`, `Absent`, `Open`, `Closed`).
- `FeedbackAlert` variant selection aligns with reason semantics.

### 5.2 Identity and roster

- `IdentityCell` combines avatar and text for quick recognition in dense tables.
- Optional compact mode for mobile and narrow side panels.

### 5.3 Action safety

- `ConfirmActionModal` required for close session, destructive edits, and high-impact actions.
- Mutations should return local component feedback plus page-level confirmation.

## 6. Token and module references

| Component | Tokens/modules to follow |
| --- | --- |
| `FeedbackAlert` | `design-system/alerts.md` |
| `StatusBadge` | `design-system/badges.md` |
| `IdentityCell` | `design-system/avatars.md` |
| `CollapsibleDetail` patterns | `design-system/accordion.md` |
| `TableToolbar` and `DataTable` | `design-system/tables.md`, `design-system/pagination.md` |

## 7. Component traceability

| Component concern | Requirement links |
| --- | --- |
| Check-in failure clarity | `FR-22`, `BR-23`, `AC-18` |
| Session control confidence | `FR-07`, `FR-14`, `AC-01` |
| Manual correction UX | `FR-20`, `BR-14`, `AC-13` |
| Listing/report productivity | `FR-28`, `AC-UI-07` |
| Permission-safe interactions | `FR-27`, `FR-32`, `BR-19` |

## 8. Future consideration

- Configurable toolbar presets per role.
- Bulk-edit workflows with safer preview and approval layers.
