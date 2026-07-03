# Attendly — Production UI Quality Bar

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [DESIGN.md](./DESIGN.md) · [01-design-overview.md](./01-design-overview.md) · [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md) · [05-common-ui-components.md](./05-common-ui-components.md) · [06-app-layout-components.md](./06-app-layout-components.md)

## 1. Purpose and scope

This document defines production-readiness quality gates for Attendly UI/UX across student, lecturer, admin, and auditor surfaces.

### 1.1 Quality principles

- `NFR-UI-01`: Prioritize classroom-speed interaction and low cognitive load.
- `NFR-UI-02`: Keep visual consistency through tokenized Neobrutalism rules from `DESIGN.md`.
- `NFR-UI-03`: Ensure role-safe UX that does not imply unauthorized actions.
- `NFR-UI-04`: Build accessible interactions for keyboard and mobile touch users.

## 2. MVP UI quality requirements

### 2.1 Functional clarity bar

- `FR-UI-01`: Every primary route shows one unambiguous primary action.
- `FR-UI-02`: Session state (`Scheduled`, `Open`, `Closed`, `Cancelled`) is always visible in the viewport header area.
- `FR-UI-03`: Check-in failure feedback always includes reason + next action.
- `FR-UI-04`: Manual fallback actions must require explicit confirmation and reason capture where policy requires.

### 2.2 Performance and resilience bar

- `NFR-UI-05`: Student check-in screens render meaningful content quickly on common mobile browsers.
- `NFR-UI-06`: Realtime roster updates should avoid full-page refresh and preserve scroll/selection context.
- `NFR-UI-07`: Empty, loading, and error states are required for all list/report pages.

### 2.3 Accessibility bar

- `NFR-UI-08`: Keyboard focus ring is visible on all interactive controls.
- `NFR-UI-09`: Text and status badges maintain clear contrast against their backgrounds.
- `NFR-UI-10`: Form controls use explicit labels and descriptive validation messages.
- `NFR-UI-11`: Touch target sizing supports mobile check-in interactions.

## 3. Acceptance criteria by surface

### 3.1 Student check-in surface

- `AC-UI-01`: Student can complete scan-to-result flow without navigating more than necessary.
- `AC-UI-02`: Fail states for `ExpiredQr`, `NotEnrolled`, `DuplicateCheckIn`, and GPS outcomes are visually distinct and actionable.
- `AC-UI-03`: Success state clearly displays final status (`Present` or `Late`) and timestamp.

### 3.2 Lecturer session control and roster

- `AC-UI-04`: Lecturer can identify open/close controls and session status within one screen.
- `AC-UI-05`: Rejected attempt reasons and manual correction actions are available in roster context.
- `AC-UI-06`: QR display is legible in classroom projection context.

### 3.3 Admin, reporting, and audit surfaces

- `AC-UI-07`: Listing pages provide search/filter/sort/pagination controls consistent with `TableToolbar`.
- `AC-UI-08`: Export actions show scope context before execution.
- `AC-UI-09`: Unauthorized paths present explicit permission feedback without data leakage.

## 4. Definition of done for UI implementation

### 4.1 Design system conformance

- `BR-UI-01`: Components use tokens mapped in `04-design-tokens.md`.
- `BR-UI-02`: Component visuals follow precedence: `DESIGN.md` > `design-system/*` > token mapping docs.
- `BR-UI-03`: No ad-hoc colors/shadows/radius values outside approved token set.

### 4.2 Interaction and state coverage

- `BR-UI-04`: Each interactive component includes default, hover, focus, disabled states.
- `BR-UI-05`: Async actions include loading and failure treatment.
- `BR-UI-06`: Destructive actions include confirmation and post-action feedback.

### 4.3 Content and localization

- `BR-UI-07`: Student-facing messages are concise Vietnamese copy.
- `BR-UI-08`: Error text aligns with backend reason-code semantics.

## 5. Production verification checklist

| ID | Verification item | Expected result | Trace |
| --- | --- | --- | --- |
| `CHK-UI-01` | Token usage scan | No unapproved hardcoded values | `BR-UI-01` |
| `CHK-UI-02` | Route walkthrough | Primary actions are obvious per route | `FR-UI-01` |
| `CHK-UI-03` | Accessibility test pass | Focus/labels/contrast checks pass | `NFR-UI-08` to `NFR-UI-10` |
| `CHK-UI-04` | Failure-state simulation | Check-in and export failures remain actionable | `AC-UI-02`, `AC-UI-09` |
| `CHK-UI-05` | Responsive test | Student flows remain usable on mobile widths | `NFR-UI-11` |

## 6. Acceptability rubric

### 6.1 Acceptable

- UI behavior matches role permissions and never exposes unauthorized actions as available.
- Check-in outcomes and failure reasons remain explicit, actionable, and aligned with backend reason semantics.
- Design token usage follows precedence and avoids unapproved ad-hoc visual values.
- Core mobile student and desktop staff flows pass accessibility and responsive quality checks.

### 6.2 Not acceptable

- Primary actions are ambiguous, hidden, or visually deprioritized in critical attendance workflows.
- Failure states lack recovery guidance or hide reason context from students/lecturers.
- Unauthorized actions can be triggered or appear active without scope-aware restrictions.
- Hardcoded visual values bypass the token system and create cross-route inconsistency.

## 7. Future consideration

- Optional motion system refinement for advanced dashboards.
- Higher-density analytics visualization standards for post-MVP reporting.
- Extended accessibility audits for institutional compliance profiles.
