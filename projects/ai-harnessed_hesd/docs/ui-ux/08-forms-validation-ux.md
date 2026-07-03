# Attendly — Forms and Validation UX

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md) · [05-common-ui-components.md](./05-common-ui-components.md) · [07-domain-specific-components.md](./07-domain-specific-components.md) · [09-page-list.md](./09-page-list.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../technical/05-api-design.md](../technical/05-api-design.md) · [../technical/08-validation-rules.md](../technical/08-validation-rules.md)

## 1. Purpose and scope

This document defines the **forms and validation experience** for every data-entry surface in Attendly MVP: academic setup, enrollment import, session control, manual correction, policy configuration, authentication, and the student check-in submission. It specifies field-level behavior, inline messaging, error-code mapping, and accessibility so engineers and designers implement forms without guessing.

Form controls follow the Neobrutalist grammar from [DESIGN.md](./DESIGN.md): `2px` black borders, `0px` radius, hard offset shadows, and visible focus rings — sourced from [inputs.md](./design-system/inputs.md), [dropdown.md](./design-system/dropdown.md), and [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md).

### 1.1 Form inventory

| ID | Form | Surface | Requirement trace |
| --- | --- | --- | --- |
| FRM-01 | Login | Auth entry | `FR-15`, `FR-36` |
| FRM-02 | Term create/edit | Admin setup (SUR-04) | `FR-01` |
| FRM-03 | Course create/edit | Admin setup (SUR-04) | `FR-02` |
| FRM-04 | Class section create/edit | Admin setup (SUR-04) | `FR-03`, `FR-06` |
| FRM-05 | Room/location create/edit | Admin setup (SUR-04) | `FR-05` |
| FRM-06 | Enrollment CSV import | Admin setup (SUR-04) | `FR-04` |
| FRM-07 | Attendance policy config | Admin policy (SUR-04) | `FR-24`, `FR-25` |
| FRM-08 | Manual correction | Lecturer roster (SUR-03) | `FR-20`, `FR-21` |
| FRM-09 | Session open (room override) | Lecturer session (SUR-02) | `FR-07` |
| FRM-10 | Report filter / export scope | Reporting (SUR-05) | `FR-27`, `FR-28` |
| FRM-11 | Check-in submission | Student (SUR-01) | `FR-16`, `FR-34` |

---

## 2. Validation principles

| ID | Principle | Rationale |
| --- | --- | --- |
| `FR-VAL-01` | Client validation is convenience; the server is authoritative | Prevent divergence from [08-validation-rules.md](../technical/08-validation-rules.md) |
| `FR-VAL-02` | Every field error shows what's wrong **and** how to fix it | `NFR-UI-10`, recovery-first UX |
| `FR-VAL-03` | Error copy maps to backend reason codes | `BR-UI-08`, consistent semantics with [05-api-design.md](../technical/05-api-design.md) |
| `FR-VAL-04` | No silent failure or silent row-skipping | `FR-04`, import integrity |
| `FR-VAL-05` | Validation runs in a defined order and short-circuits | mirrors check-in order in [05-api-design.md](../technical/05-api-design.md) §5.1 |
| `NFR-VAL-01` | All controls are keyboard-operable with visible focus | `NFR-UI-08` |
| `NFR-VAL-02` | Labels are explicit; placeholders never replace labels | `NFR-UI-10` |

### 2.1 Validation timing

| Trigger | Behavior |
| --- | --- |
| On blur | Validate the individual field and show inline error/success |
| On change (after first error) | Re-validate the field to clear the error as soon as it becomes valid |
| On submit | Validate the whole form, move focus to the first invalid field, and surface a summary alert |
| Server response | Map returned `error.code` to the offending field(s) or a form-level `FeedbackAlert` |

Recommended implementation: React Hook Form + Zod per [02-ui-framework-tech-stack.md](./02-ui-framework-tech-stack.md), keeping schemas aligned with server contracts.

---

## 3. Field-level UX patterns

### 3.1 Input states

Per [inputs.md](./design-system/inputs.md) and [03-design-system-basics.md](./03-design-system-basics.md) §3.2, every field supports:

| State | Visual signal |
| --- | --- |
| Default | neutral border, label above field |
| Focus | visible focus ring (`NFR-UI-08`) |
| Filled/valid | neutral or subtle success affordance |
| Error | danger border + inline message with icon ([alerts.md](./design-system/alerts.md) inline variant) |
| Disabled | reduced-emphasis, non-interactive; used for role-gated fields |
| Loading (async fields) | inline spinner for async lookups (e.g. lecturer selector) |

### 3.2 Field composition

- **Label** — always present, associated via `for`/`id`; required fields marked explicitly (not by color alone).
- **Helper text** — short guidance under the label when the field needs context (e.g. GPS radius units in meters).
- **Inline error** — replaces or sits beneath helper text; concise Vietnamese for student-facing forms.
- **Character/format hints** — for coded fields (term code, section code) show the expected format.

### 3.3 Control selection

| Data shape | Control | Module |
| --- | --- | --- |
| Free text / codes | text input | [inputs.md](./design-system/inputs.md) |
| Single choice from set | dropdown/select | [dropdown.md](./design-system/dropdown.md) |
| Boolean policy flag (e.g. GPS required) | toggle | [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md) |
| Small mutually exclusive set | radio group | [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md) |
| Date / date-time | date input | [inputs.md](./design-system/inputs.md) |
| File (CSV) | file upload zone | [inputs.md](./design-system/inputs.md) |

---

## 4. Form specifications

### 4.1 Login (FRM-01)

Trace: `FR-15`, `FR-36`.

| Field | Rules | Error copy (vi-VN) |
| --- | --- | --- |
| Email/identifier | required, format-checked | "Vui lòng nhập email hợp lệ." |
| Password | required | "Vui lòng nhập mật khẩu." |

- Repeated failures throttle/lock per security policy (`FR-36`); the form shows a neutral "thử lại sau" message without revealing which field was wrong (avoid account enumeration).
- On success, unauthenticated users who arrived via a check-in link return to check-in (`FR-15`).
- Maps `401 Unauthenticated` to a form-level alert, never a silent redirect loop.

### 4.2 Class section create/edit (FRM-04)

Trace: `FR-03`, `FR-06`.

| Field | Rules |
| --- | --- |
| Section code | required, unique within term; format hint shown |
| Term | required; dropdown of active terms |
| Course | required; searchable dropdown |
| Assigned lecturer | required; async lecturer lookup |
| Default room | optional (required when GPS policy enabled) |
| Schedule template | day-of-week, start time, duration; validated as a coherent time block |

- Server conflicts (duplicate section code) map to the section-code field, not a generic alert.
- Only `AcademicAdmin` (and scoped `DepartmentAdmin` when enabled) see write controls; others see read-only fields (`PRM-04`, `NFR-UI-03`).

### 4.3 Enrollment CSV import (FRM-06)

Trace: `FR-04`, `BR-06`. This is the highest-risk form for data integrity.

| Stage | UX behavior |
| --- | --- |
| Upload | File-drop zone accepts `.csv`; shows file name and size |
| Pre-validation | Client checks required columns (student identifier, section reference) before submit |
| Submit | Calls `POST /v1/enrollments/import`; shows loading state |
| Result | Renders `acceptedRows` count **and** a row-level error table — never silently skips invalid rows (`FR-VAL-04`) |

Row-error table columns: row number, error code (e.g. `StudentNotFound`), and message. The user can correct the source file and re-import. Partial-success is explicit: accepted rows are applied; rejected rows are listed for correction.

### 4.4 Attendance policy config (FRM-07)

Trace: `FR-24`, `FR-25`.

| Field | Rules |
| --- | --- |
| Scope level | radio: institution / faculty / course / section |
| Present window | duration; must be ≥ 0 and precede late window end |
| Late window | duration; must not overlap invalidly with present window |
| Auto-close rule | derived from late window; validated as consistent |
| Absence threshold | percentage 0–100 |
| Excused-absence handling | toggle: count toward absence or not |
| Manual-edit window | duration lecturers may edit after session |
| GPS required | toggle |
| GPS radius (m) | integer; default `100`; only editable when GPS required is on |

- Cross-field validation prevents contradictory windows (present window after late window, etc.).
- The resulting effective policy is previewed via `PolicyResolutionSummary` (see [07-domain-specific-components.md](./07-domain-specific-components.md) §5.1) so admins see precedence resolution before saving.

### 4.5 Manual correction (FRM-08)

Trace: `FR-20`, `FR-21`, `BR-14`, `BR-15`, `BR-16`. Rendered inside `ManualCorrectionDialog`.

| Field | Rules |
| --- | --- |
| New status | required; limited to policy-allowed `attendanceStatus` values |
| Reason | required when policy mandates (`FR-20`); min length enforced |

- Scope violation → `403 OutOfScope` mapped to a form-level danger alert with no submit.
- Edit-window expiry → `409 EditWindowExpired` mapped to escalation guidance (request admin action) rather than a raw error.
- On success, the audit entry (old → new, actor, reason) is written server-side (`FR-29`).

### 4.6 Check-in submission (FRM-11)

Trace: `FR-16`, `FR-34`. This is a latency-critical, near-zero-field "form".

- The only optional user-provided input is GPS consent via `GpsPermissionPrompt`; the QR token is carried by the scanned URL.
- Client-side validation is minimal by design to keep the flow fast (`NFR-UI-05`); the server owns all rule evaluation.
- All outcomes render through `CheckInResultScreen` (see [07-domain-specific-components.md](./07-domain-specific-components.md) §3.1) with reason + next action (`FR-UI-03`).

---

## 5. Error-code to UX mapping

The UI maps API error codes from [05-api-design.md](../technical/05-api-design.md) §2.4 / §3.2 to placement and copy. This is the authoritative mapping for form and check-in messaging.

| HTTP / code | Placement | Student/Staff copy intent |
| --- | --- | --- |
| `400 InvalidPayload` | field-level where resolvable, else form alert | "Dữ liệu chưa hợp lệ, vui lòng kiểm tra lại." |
| `400 MalformedQrToken` | check-in result screen | "Mã QR không hợp lệ. Vui lòng quét lại." |
| `401 Unauthenticated` | login redirect + form alert | "Vui lòng đăng nhập để tiếp tục." |
| `403 Forbidden` / `OutOfScope` | form/page alert, hide submit | "Bạn không có quyền thực hiện thao tác này." |
| `404 SessionNotFound` | page alert | "Không tìm thấy buổi học." |
| `409 DuplicateCheckIn` | check-in result screen | "Bạn đã điểm danh buổi học này rồi." |
| `409 InvalidSessionTransition` | session control alert | "Không thể thực hiện thao tác cho trạng thái hiện tại." |
| `409 EditWindowExpired` | correction dialog | escalation guidance to admin |
| `422 ExpiredQr` | check-in result screen | "Mã QR đã hết hạn. Vui lòng quét mã mới." |
| `422 NotEnrolled` | check-in result screen | "Bạn không thuộc lớp học phần này." |
| `422 OutOfRadius` / `LowAccuracy` / `GpsDisabled` | check-in result + GPS prompt | location guidance (risk-reduction framing) |
| `429 TooManyRequests` | form/page alert | "Bạn thao tác quá nhanh, vui lòng thử lại sau." |
| `500 InternalError` | form/page alert + retry | "Có lỗi hệ thống. Vui lòng thử lại." |

Rule: field-resolvable errors bind to their field; scope and system errors surface as a `FeedbackAlert` at form or page level (see [05-common-ui-components.md](./05-common-ui-components.md)).

---

## 6. Accessibility and localization

- **Labels & associations:** every control has a programmatic label; errors are announced via `aria-live` regions (`NFR-UI-10`).
- **Focus management:** on submit failure, focus moves to the first invalid field; on dialog open, focus is trapped and returned on close ([modals.md](./design-system/modals.md)).
- **Contrast:** error/success states rely on icon + text, not color alone (`NFR-UI-09`).
- **Touch sizing:** student form controls meet mobile touch-target minimums (`NFR-UI-11`).
- **Localization:** student-facing copy is concise Vietnamese (`vi-VN`); admin/technical labels may use English identifiers where clearer (`BR-UI-07`).

---

## 7. Traceability

| Form/validation concern | FR | BR | AC / NFR |
| --- | --- | --- | --- |
| Enrollment import integrity | `FR-04` | `BR-06` | `AC-UI-07` |
| Manual correction governance | `FR-20`, `FR-21` | `BR-14` to `BR-16` | `AC-13`, `AC-14` |
| Policy configuration consistency | `FR-24`, `FR-25` | `BR-11`, `BR-12`, `BR-13` | — |
| Check-in feedback recoverability | `FR-16`, `FR-22` | `BR-05` to `BR-12` | `AC-UI-02`, `FR-UI-03` |
| Accessible, labeled forms | — | — | `NFR-UI-08` to `NFR-UI-11` |

---

## 8. Future consideration

- Inline duplicate-detection for enrollment import before submit.
- Reusable async validators shared with backend Zod-derived schemas.
- Guided multi-step wizard for first-time term/course/section setup.
