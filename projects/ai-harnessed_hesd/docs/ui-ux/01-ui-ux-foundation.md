# Attendly — UI/UX Foundation

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md) · [01-design-overview.md](./01-design-overview.md) · [DESIGN.md](./DESIGN.md) · [03-design-system-basics.md](./03-design-system-basics.md) · [06-app-layout-components.md](./06-app-layout-components.md)

## 1. Foundation objectives

This document defines shared UI/UX foundations that all Attendly routes must follow.

### 1.1 Foundation requirements

- `FR-FND-01`: Preserve consistent role-aware interaction patterns across all modules.
- `FR-FND-02`: Ensure state-driven feedback in attendance-critical flows.
- `FR-FND-03`: Provide mobile-first resilience for student check-in.
- `FR-FND-04`: Keep admin surfaces efficient for high-volume list operations.

## 2. Design principles

### 2.1 Operational clarity

- `BR-FND-01`: Primary actions are visually dominant and context-specific.
- `BR-FND-02`: Status is always visible where decisions are made.
- `BR-FND-03`: Error states include explicit recovery instructions.

### 2.2 Consistency through systemization

- `BR-FND-04`: Visual and interaction semantics are tokenized.
- `BR-FND-05`: Component behavior is inherited from design-system modules.
- `BR-FND-06`: Route-level composition must not break component-level rules.

### 2.3 Trust and governance

- `NFR-FND-01`: UI must not imply capabilities beyond role permissions.
- `NFR-FND-02`: Mutation actions must present confirmatory feedback.
- `NFR-FND-03`: Export and correction workflows emphasize auditability.

## 3. Foundational UX patterns

### 3.1 State-first UI pattern

| Pattern | Description | Example |
| --- | --- | --- |
| Session state marker | Persistent status badge/chip in page header | `Open` session control view |
| Result feedback | Immediate success/failure block after action | Check-in submit result |
| Action lock | Disable invalid actions by state | Hide `Open` when session already open |
| Recovery prompt | Secondary action for blocked flows | Re-scan QR on token expiry |

### 3.2 Form and validation pattern

- Inline validation for local input errors.
- Summary alert for submission-level failures.
- Required labels and clear helper text for policy-sensitive controls.
- Disabled states for unauthorized or out-of-window actions.

### 3.3 Listing interaction pattern

- Shared `TableToolbar` for search/filter/sort bulk actions.
- Stable table row density and badge semantics.
- Pagination with explicit current range visibility.

## 4. Accessibility and interaction baseline

### 4.1 Core interaction requirements

- `NFR-FND-04`: Keyboard operability for all staff interactions.
- `NFR-FND-05`: Focus visibility on all actionable elements.
- `NFR-FND-06`: Mobile touch targets suitable for student check-in.
- `NFR-FND-07`: Informative empty states and non-blocking loading placeholders.

### 4.2 Language and messaging baseline

- Student-facing flows default to concise Vietnamese copy.
- Operational identifiers may remain English where necessary for technical clarity.
- Error copy mirrors backend reason semantics for support alignment.

## 5. Foundation route archetypes

| Archetype | Route examples | Layout type | Core components |
| --- | --- | --- | --- |
| Mobile transactional | Student check-in and result views | Minimal top-level shell | Form input, alerts, primary CTA |
| Operational control | Lecturer session + roster | Split panel shell | Status badges, table, inline actions |
| Governance listing | Admin reporting/policy | Standard app shell | `TableToolbar`, table, pagination, drawer/modal |
| Evidence review | Audit and dispute pages | Data-dense shell | Filters, timeline/list, detail accordion |

## 6. Foundation traceability

| Foundation item | BRD/technical link |
| --- | --- |
| Role-safe controls | `FR-27`, `FR-32`, `BR-19` |
| Check-in feedback semantics | `FR-22`, `BR-23`, `AC-18` |
| Session control clarity | `FR-07`, `FR-14`, `AC-01` |
| Manual fallback usability | `FR-20`, `BR-14`, `AC-13` |
| Performance-sensitive student flow | `NFR-01`, `NFR-14` |

## 7. Future consideration

- Personalizable lecturer dashboard panels.
- Additional dense data-entry patterns for bulk corrections.
- Advanced visualization grammar for cross-campus analytics.
