# Attendly — App Layout Components

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [DESIGN.md](./DESIGN.md) · [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) · [05-common-ui-components.md](./05-common-ui-components.md)

## 1. Purpose

Define app-level layout components and composition rules for student and staff route families.

## 2. Layout architecture

### 2.1 Layout families

| Layout ID | Family | Primary routes | Characteristics |
| --- | --- | --- | --- |
| `LAY-01` | Student mobile transactional | Check-in and outcome routes | Minimal chrome, clear vertical flow |
| `LAY-02` | Lecturer operational shell | Session control and live roster | Context-rich header, action rail, data panel |
| `LAY-03` | Admin governance shell | Management/reporting routes | Persistent navigation + table-first content region |
| `LAY-04` | Audit evidence shell | Audit logs and dispute review | Dense filters + detail panel with progressive disclosure |

### 2.2 Layout composition rules

- `FR-LAY-01`: Page title and state marker must be present in shell header.
- `FR-LAY-02`: Primary actions remain in predictable placement within each layout family.
- `FR-LAY-03`: Content width and spacing follow shared layout tokens.
- `FR-LAY-04`: Layouts support responsive collapse without losing critical controls.

## 3. Core layout components

| Component | Purpose | Used in |
| --- | --- | --- |
| `AppShell` | Master scaffold with nav, header, and content region | `LAY-02`, `LAY-03`, `LAY-04` |
| `TopContextHeader` | Route title, breadcrumbs, status badges, key actions | All staff layouts |
| `SidebarNav` | Role-specific route access and grouping | Staff layouts |
| `ContentSection` | Consistent section spacing and grouping | All layouts |
| `SplitPanel` | Dual-pane operational view (table + detail) | Lecturer and audit layouts |
| `MobileFlowContainer` | Narrow-width transactional wrapper | `LAY-01` |
| `ActionBar` | Local route actions and filters | Staff list and detail routes |

## 4. Responsive behavior

### 4.1 Breakpoint guidance

- Mobile first for student routes.
- Tablet and desktop optimized for lecturer/admin operational density.
- Sidebar collapses to drawer where viewport constraints require it.

### 4.2 Responsive requirements

- `NFR-LAY-01`: No critical action should become unreachable after layout collapse.
- `NFR-LAY-02`: Table actions remain available through responsive toolbar patterns.
- `NFR-LAY-03`: Mobile check-in flow avoids horizontal scrolling.

## 5. Route-level layout mapping

| Route domain | Preferred layout | Required components |
| --- | --- | --- |
| Student check-in | `LAY-01` | `MobileFlowContainer`, `FeedbackAlert`, primary CTA |
| Lecturer session control | `LAY-02` | `TopContextHeader`, QR control panel, `SplitPanel` roster |
| Lecturer roster and corrections | `LAY-02` | `ActionBar`, `DataTable`, correction panel/modal |
| Admin list/reporting | `LAY-03` | `SidebarNav`, `TopContextHeader`, `TableToolbar`, pagination |
| Audit/dispute review | `LAY-04` | filter-heavy `ActionBar`, timeline/list, accordion detail |

## 6. Layout interaction and state handling

### 6.1 State visibility

- `FR-LAY-05`: Session state and permission context must stay visible in staff headers.
- `FR-LAY-06`: Route-level loading/error/empty states are mandatory.
- `FR-LAY-07`: High-risk actions use confirm patterns and post-action feedback.

### 6.2 Permission-aware rendering

- Hide non-applicable navigation items by role.
- Disable or remove out-of-scope actions in context.
- Show explicit permission feedback when user reaches a restricted flow.

## 7. Accessibility and navigation requirements

- `NFR-LAY-04`: Landmark structure supports screen-reader navigation.
- `NFR-LAY-05`: Keyboard tab order follows visual order in shells and sidebars.
- `NFR-LAY-06`: Focus restoration occurs after modal close and route action completion.

## 8. Traceability

| Layout concern | Requirement links |
| --- | --- |
| Session operation speed | `FR-07`, `FR-19`, `NFR-01` |
| Student check-in clarity | `FR-16`, `FR-23`, `NFR-14` |
| Permission-safe admin surfaces | `FR-27`, `FR-32`, `BR-19` |
| Manual fallback support | `FR-20`, `BR-14`, `AC-13` |

## 9. Future consideration

- Role-customizable dashboards within a shared shell contract.
- Multi-campus navigation variants for expanded deployments.
