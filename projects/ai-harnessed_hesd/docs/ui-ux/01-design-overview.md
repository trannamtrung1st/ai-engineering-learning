# Attendly — Design Overview

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [DESIGN.md](./DESIGN.md) · [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) · [02-ui-framework-tech-stack.md](./02-ui-framework-tech-stack.md) · [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md)

## 1. Product UX intent

Attendly UI focuses on operational clarity during time-sensitive attendance windows while preserving governance confidence for admins and auditors.

### 1.1 Experience goals

- `FR-OV-01`: Students complete check-in quickly with clear status outcomes.
- `FR-OV-02`: Lecturers control session lifecycle and exception handling without ambiguity.
- `FR-OV-03`: Admin users manage policy/reporting with predictable table workflows.
- `FR-OV-04`: All roles receive clear permission feedback for out-of-scope actions.

## 2. User surfaces and UX posture

| Surface | Primary actor | UX posture | Requirement links |
| --- | --- | --- | --- |
| Student check-in | Student | Mobile-first, low-friction, high feedback clarity | `FR-15`, `FR-16`, `FR-23`, `AC-06`, `AC-11` |
| Session control | Lecturer | Fast action + live status confidence | `FR-07`, `FR-11`, `FR-14`, `AC-01`, `AC-02` |
| Live roster/manual fallback | Lecturer | Dense but scannable operations view | `FR-19`, `FR-20`, `BR-14`, `AC-13` |
| Admin management | Academic Admin / Department Admin | Structured listing/edit patterns | `FR-01` to `FR-06`, `FR-24` |
| Reports and audit | Lecturer/Admin/Auditor | Scope-safe filtering and evidence visibility | `FR-27`, `FR-30`, `FR-32`, `AC-17` |

## 3. Visual language summary

### 3.1 Core style

- `BR-OV-01`: Neobrutalism with strong contrast and hard offset shadows.
- `BR-OV-02`: Borders are explicit and structural, not decorative.
- `BR-OV-03`: Radius defaults to square geometry except explicit pill/circle patterns.
- `BR-OV-04`: Typography prioritizes bold, high-legibility control points.

Authoritative reference: `DESIGN.md` and `design-system/` modules.

### 3.2 Semantic visual signaling

| Semantic intent | Typical usage |
| --- | --- |
| Success | Valid check-in, completed actions, healthy state |
| Warning | Late status, review-needed guidance |
| Danger | Rejections, denied actions, destructive operations |
| Neutral/brand | Informational and structural context |

## 4. Core UX patterns

### 4.1 Decision-path clarity

- `NFR-OV-01`: Every route has a clear primary action and bounded secondary actions.
- `NFR-OV-02`: Outcomes are visible immediately after mutation actions.
- `NFR-OV-03`: Recovery guidance is mandatory for error states.

### 4.2 Listing UX baseline

- `FR-OV-05`: Listing pages use consistent search/filter/sort/pagination conventions.
- `FR-OV-06`: Toolbar and table actions must map to role permissions.
- `FR-OV-07`: Empty and no-result states must be explicit and informative.

Reference: [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) and [05-common-ui-components.md](./05-common-ui-components.md).

## 5. Information architecture baseline

### 5.1 Primary route groups

- Auth and entry routes.
- Student check-in and personal attendance history.
- Lecturer session and roster workflows.
- Admin setup/policy and reporting.
- Audit/evidence review.

### 5.2 Navigation assumptions

- Student routes use simplified top-level navigation.
- Staff routes use persistent shell layout with context-aware secondary navigation.
- Critical actions are kept in stable locations across routes.

## 6. Quality and traceability

| Quality requirement | UX implication | Trace |
| --- | --- | --- |
| `NFR-01` and `NFR-02` | UI flow minimizes unnecessary steps and blocking modals | Student and lecturer workflows |
| `NFR-09` and `BR-19` | UI gates hidden/disabled actions by scope and communicates denials | Listing and export surfaces |
| `NFR-13` and `BR-23` | Failure feedback aligns with structured reason semantics | Check-in and admin actions |
| `NFR-14` | Mobile-first copy and control sizing for check-in | Student route design |

## 7. Future consideration

- Advanced cross-term analytics visualizations.
- Role-personalized dashboard modules.
- Enhanced dispute investigation workbench patterns.
