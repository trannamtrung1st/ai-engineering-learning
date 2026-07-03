# Attendly — UI/UX Design Specification (Authoritative)

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [../product-meta.json](../product-meta.json) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md) · [../technical/05-api-design.md](../technical/05-api-design.md)

## 1. Purpose and Visual Direction

### 1.1 Design intent

Attendly uses a **Neobrutalism** visual language: hard offset shadows, 2px to 3px black borders, strong contrast, and near-zero corner radius. The UI should feel decisive and operational, especially for high-pressure classroom check-in moments (`FR-07`, `FR-16`, `NFR-14`).

### 1.2 MVP UX outcomes

| Goal | UX requirement | Trace |
| --- | --- | --- |
| Fast student check-in | Student can scan QR, resolve validation feedback, and complete check-in quickly on mobile web | `FR-16`, `FR-23`, `AC-11`, `NFR-01` |
| Clear lecturer control | Lecturer can open/close attendance, monitor live roster state, and apply manual fallback confidently | `FR-07`, `FR-19`, `FR-20`, `AC-01`, `AC-13` |
| Trustworthy admin governance | Admin and auditor views communicate role scope, export actions, and audit context clearly | `FR-27`, `FR-30`, `FR-32`, `AC-16`, `AC-17` |

### 1.3 Design boundaries

- Preserve MVP scope from [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md); advanced anti-fraud visuals stay out of core flows.
- GPS UI copy must communicate risk reduction, not absolute anti-spoof guarantees (`BR-08`, `BR-09`, `NFR-11`).
- Student flow is mobile-first; lecturer/admin flows are desktop-first but responsive.

## 2. Precedence and Consumption Rules

### 2.1 Spec precedence chain

1. This file (`DESIGN.md`) is the authoritative visual index and decision layer.
2. `design-system` modules define component-level specs.
3. Token-to-CSS variable mapping is maintained in `04-design-tokens.md`.
4. Overview narrative belongs in `01-design-overview.md`.

### 2.2 Non-negotiable implementation rules

- **Token semantics:** tokens are design tokens, not framework utility class names.
- **Cross-module composition:** a composite view must satisfy all relevant component modules.
- **State coverage:** every interactive control includes hover, focus, disabled, and loading/error states as applicable.
- **Semantic structure:** use accessible headings, landmarks, labels, and focus management for keyboard navigation.

## 3. Product Surface Map

### 3.1 Primary surfaces

| Surface ID | Route or view intent | Primary actors | Key states | Requirement trace |
| --- | --- | --- | --- | --- |
| SUR-01 | Student QR entry and check-in result | Student | loading, success, failure reason, retry | `FR-15`, `FR-16`, `FR-22`, `AC-06`, `AC-18` |
| SUR-02 | Lecturer session control (open/close + rotating QR) | Lecturer | scheduled, open, closed, token refresh | `FR-07`, `FR-11`, `FR-14`, `AC-01`, `AC-02` |
| SUR-03 | Lecturer live roster and manual fallback | Lecturer | present/late/pending/rejected/manual | `FR-19`, `FR-20`, `BR-14`, `AC-13` |
| SUR-04 | Academic admin structure and policy management | AcademicAdmin | list/filter/edit forms/validation | `FR-01` to `FR-06`, `FR-24` |
| SUR-05 | Reporting/export and audit review | Lecturer/Admin/Auditor | filter/sort/export/history | `FR-27`, `FR-30`, `FR-32`, `AC-17` |

### 3.2 State signal standards

| Domain state | Visual signal |
| --- | --- |
| `Scheduled` | neutral badge + actionable primary CTA for open flow |
| `Open` | high-emphasis success/brand indicator + realtime motion-safe updates |
| `Closed` | dark or neutral locked state; destructive actions hidden |
| Failed check-in outcomes | alert pattern with clear reason and next action |

## 4. Surface-to-Token Mapping

### 4.1 Global token posture

| Category | Token intent |
| --- | --- |
| Typography | bold heading tokens for control points; readable body for guidance |
| Borders | `2px` default border tokens on all cards, controls, and table containers |
| Radius | `0px` default except explicit pill/circle patterns (badges, avatars) |
| Shadows | hard offset shadow tokens only; no blur-based elevation |
| Color roles | semantic intent through brand, success, danger, warning, neutral families |

### 4.2 Per-surface token mapping

| Surface ID | Container and layout tokens | Primary interaction tokens | Feedback and status tokens | Component module anchors |
| --- | --- | --- | --- | --- |
| SUR-01 | neutral soft background + strict spacing rhythm | primary button/input tokens for scan continuation and submit | alert tokens for `ExpiredQr`, `NotEnrolled`, `DuplicateCheckIn`, GPS outcomes | [inputs.md](./design-system/inputs.md), [buttons.md](./design-system/buttons.md), [alerts.md](./design-system/alerts.md) |
| SUR-02 | high-contrast session panel with thick border and hard shadow | prominent open/close CTAs, countdown emphasis | warning/danger states for invalid session transitions | [cards.md](./design-system/cards.md), [buttons.md](./design-system/buttons.md), [badges.md](./design-system/badges.md) |
| SUR-03 | roster table/card blocks with clear row density | row actions for manual correction | badge + alert combinations for rejected/suspicious attempts | [tables.md](./design-system/tables.md), [badges.md](./design-system/badges.md), [alerts.md](./design-system/alerts.md) |
| SUR-04 | list/detail forms with dense but readable admin layout | form validation and action bars | inline and summary validation alerts | [inputs.md](./design-system/inputs.md), [dropdown.md](./design-system/dropdown.md), [alerts.md](./design-system/alerts.md) |
| SUR-05 | report table shells and filter toolbar patterns | filter/sort/pagination controls | export confirmation and permission-denied alerts | [tables.md](./design-system/tables.md), [pagination.md](./design-system/pagination.md), [alerts.md](./design-system/alerts.md) |

### 4.3 Tokenized status palette policy

- `Present` and successful operations use success token families.
- `Late` uses warning token families.
- `Absent` and denial outcomes use danger token families.
- Informational policy guidance uses brand or neutral soft families.

## 5. Component-Level Authoritative Notes

### 5.1 Alerts

Use `alerts.md` as the single source for message styling.  
Required usage:
- Inline validation failures on forms.
- Check-in outcome feedback screens.
- Export/audit operation confirmations and failures.

### 5.2 Badges

Use `badges.md` for session and attendance status chips across tables/cards.  
Required usage:
- Session state chips (`Scheduled`, `Open`, `Closed`).
- Attendance states (`Present`, `Late`, `Absent`, `Manual Present`, `Excused`).

### 5.3 Avatars

Use `avatars.md` for people identity blocks in lecturer and admin surfaces; keep rounded-square default for system consistency unless explicit circular usage is required in compact roster contexts.

### 5.4 Accordion

Use `accordion.md` for dense policy explanation blocks, audit context panels, and collapsible detail rows where progressive disclosure improves scan speed.

## 6. Accessibility and Interaction Standards

### 6.1 Interaction minimums

- Visible focus indicators on all interactive controls.
- Touch target sizing suitable for mobile check-in flow.
- Keyboard-operable controls for staff workflows.
- Motion kept purposeful and brief; avoid distracting transitions during live attendance operations.

### 6.2 Content and language standards

- Student-facing copy is concise Vietnamese (`vi-VN`) with action-oriented error recovery guidance.
- System/technical naming in admin surfaces can use English identifiers where needed.
- Error and status terms must align with API outcome codes and BRD state names (`FR-22`, `BR-23`).

## 7. Traceability Matrix (Visual to Requirements)

| Visual requirement | FR | BR | AC | NFR |
| --- | --- | --- | --- | --- |
| QR interaction clarity and status immediacy | `FR-11`, `FR-14` | `BR-03`, `BR-04` | `AC-02`, `AC-04` | `NFR-01` |
| Mobile check-in usability | `FR-16`, `FR-23` | `BR-05` to `BR-12` | `AC-06` to `AC-11` | `NFR-14` |
| Rejection-path recoverability | `FR-22` | `BR-23` | `AC-18` | `NFR-13` |
| Manual fallback clarity and confidence | `FR-20`, `FR-21` | `BR-14` to `BR-16` | `AC-13`, `AC-14` | `NFR-17` |
| Role-scoped report/export affordances | `FR-27`, `FR-30`, `FR-32` | `BR-18`, `BR-19` | `AC-15`, `AC-16`, `AC-17` | `NFR-09`, `NFR-10` |

## 8. Module Index

### 8.1 Foundation modules

- [colors.md](./design-system/colors.md)
- [typography.md](./design-system/typography.md)
- [layout.md](./design-system/layout.md)
- [radius.md](./design-system/radius.md)
- [shadows.md](./design-system/shadows.md)
- [borders.md](./design-system/borders.md)

### 8.2 Core component modules

- [buttons.md](./design-system/buttons.md)
- [button-group.md](./design-system/button-group.md)
- [cards.md](./design-system/cards.md)
- [inputs.md](./design-system/inputs.md)
- [alerts.md](./design-system/alerts.md)
- [badges.md](./design-system/badges.md)
- [avatars.md](./design-system/avatars.md)
- [lists.md](./design-system/lists.md)
- [icon-shapes.md](./design-system/icon-shapes.md)

### 8.3 Complex component modules

- [accordion.md](./design-system/accordion.md)
- [dropdown.md](./design-system/dropdown.md)
- [modals.md](./design-system/modals.md)
- [tabs.md](./design-system/tabs.md)
- [tables.md](./design-system/tables.md)
- [pagination.md](./design-system/pagination.md)
- [sidebars.md](./design-system/sidebars.md)
- [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md)
- [tooltips-popovers.md](./design-system/tooltips-popovers.md)
- [content.md](./design-system/content.md)

## 9. Future Consideration

- Enhanced design states for optional anti-fraud workflows beyond MVP.
- Advanced data-visualization patterns for cross-term analytics dashboards.
- Expanded accessibility audits with institution-specific compliance baselines.
