# Attendly — Design System Basics

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [04-design-tokens.md](./04-design-tokens.md) · [05-common-ui-components.md](./05-common-ui-components.md) · [06-app-layout-components.md](./06-app-layout-components.md)

## 1. Purpose

Define base rules for using Attendly design system modules consistently across all UI surfaces.

## 2. Precedence chain

### 2.1 Source-of-truth order

1. `DESIGN.md` (authoritative visual decisions and route mapping)
2. `design-system/*.md` component and foundation modules
3. `04-design-tokens.md` token-to-CSS variable mapping
4. `01-design-overview.md` narrative guidance
5. Harness visual guidance only when the above sources are silent

### 2.2 Governance rule

- `BR-DS-01`: When conflicts occur, implement the highest-precedence source and document deviations in implementation notes.

## 3. Design-system fundamentals

### 3.1 Visual grammar

- Hard borders and hard shadows are structural.
- Default radius is square (`0px`) except explicit pill/circle variants.
- Typography hierarchy emphasizes fast scanning in operational contexts.
- Semantic color usage drives status understanding.

### 3.2 Interaction grammar

- Required states: default, hover, focus, disabled.
- Async-capable controls also require loading and error treatment.
- State feedback must be immediate and consistent across routes.

## 4. Foundational modules

| Module group | Key files | Baseline usage |
| --- | --- | --- |
| Color and semantics | `colors.md` | All status and feedback patterns |
| Type and content | `typography.md`, `content.md` | Readability and hierarchy |
| Geometry | `radius.md`, `borders.md`, `shadows.md` | Neobrutalist structural style |
| Layout | `layout.md`, `sidebars.md` | Shells and spacing consistency |

## 5. Core component modules

| Component | Source module | Required usage contexts |
| --- | --- | --- |
| Alert | `alerts.md` | Check-in failures, policy warnings, export feedback |
| Badge | `badges.md` | Session and attendance status indicators |
| Avatar | `avatars.md` | User identity context in lists/headers |
| Accordion | `accordion.md` | Progressive disclosure in audit/policy details |
| Input/Dropdown/Toggle | `inputs.md`, `dropdown.md`, `radios-checkboxes-toggle.md` | Form-heavy admin and setup routes |
| Table/Pagination | `tables.md`, `pagination.md` | Listing/reporting workflows |

## 6. Token and implementation rules

### 6.1 Token requirements

- `FR-DS-01`: Components must consume semantic tokens, not raw color literals.
- `FR-DS-02`: Spacing and sizing values should follow shared token scales.
- `FR-DS-03`: CSS variable mappings from `04-design-tokens.md` are required for implementation portability.

### 6.2 Accessibility requirements

- `NFR-DS-01`: Focus ring visibility is mandatory.
- `NFR-DS-02`: Text contrast and status readability are mandatory.
- `NFR-DS-03`: Interactive controls must remain operable by keyboard.

## 7. Compliance checklist

| ID | Check | Pass condition |
| --- | --- | --- |
| `CHK-DS-01` | Precedence compliance | No implementation contradicts higher-precedence docs |
| `CHK-DS-02` | Token usage | No ad-hoc visual constants in component styles |
| `CHK-DS-03` | Component state coverage | Required states are implemented and tested |
| `CHK-DS-04` | Accessibility baseline | Focus, labels, and contrast checks pass |
| `CHK-DS-05` | Cross-route consistency | Same component intent renders consistently in student and staff routes |

## 8. Future consideration

- Expanded accessibility motion/animation standards.
- Additional guidance for complex data visualizations.
- Design system governance workflow with release versions.
