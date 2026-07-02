# Attendly — Domain-Specific Components

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md) · [05-common-ui-components.md](./05-common-ui-components.md) · [06-app-layout-components.md](./06-app-layout-components.md) · [08-forms-validation-ux.md](./08-forms-validation-ux.md) · [09-page-list.md](./09-page-list.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../technical/05-api-design.md](../technical/05-api-design.md)

## 1. Purpose and scope

This document specifies the **domain-specific components** unique to Attendly's attendance workflows. These sit above the generic primitives in [05-common-ui-components.md](./05-common-ui-components.md) (e.g. `StatusBadge`, `FeedbackAlert`, `TableToolbar`, `DataTable`) and below full page compositions in [09-page-list.md](./09-page-list.md).

### 1.1 Precedence

Component visuals follow the chain established in [03-design-system-basics.md](./03-design-system-basics.md):

1. [DESIGN.md](./DESIGN.md) — authoritative visual decisions and surface mapping.
2. [design-system/](./design-system/) modules — component-level styling.
3. [04-design-tokens.md](./04-design-tokens.md) — token-to-CSS-variable mapping.
4. [01-design-overview.md](./01-design-overview.md) — narrative guidance.
5. Harness visual guidance only when the above are silent.

Every component below is Neobrutalist by default: `2px` black borders, `0px` radius (except explicit pill/circle patterns), and hard offset shadows with no blur, per [DESIGN.md](./DESIGN.md) §4.1.

### 1.2 Component inventory

| ID | Component | Primary surface | Requirement trace |
| --- | --- | --- | --- |
| DC-01 | `QrDisplayPanel` | Lecturer session control (SUR-02) | `FR-11`, `FR-14`, `AC-UI-06` |
| DC-02 | `QrCountdownRing` | Lecturer session control (SUR-02) | `FR-11`, `FR-12`, `AC-02` |
| DC-03 | `SessionControlBar` | Lecturer session control (SUR-02) | `FR-07`, `FR-08`, `FR-10` |
| DC-04 | `CheckInResultScreen` | Student check-in (SUR-01) | `FR-16`, `FR-22`, `FR-23`, `AC-UI-02` |
| DC-05 | `GpsPermissionPrompt` | Student check-in (SUR-01) | `FR-34`, `FR-35`, `BR-08` |
| DC-06 | `LiveRosterPanel` | Lecturer roster (SUR-03) | `FR-19`, `AC-UI-05` |
| DC-07 | `AttendanceStatusCell` | Roster, reports (SUR-03/05) | `FR-19`, `FR-23` |
| DC-08 | `ManualCorrectionDialog` | Lecturer roster (SUR-03) | `FR-20`, `FR-21`, `BR-14`, `AC-13` |
| DC-09 | `PolicyResolutionSummary` | Admin policy (SUR-04) | `FR-24`, `FR-25` |
| DC-10 | `AttendanceHistoryList` | Student self-service (SUR-01) | `FR-37` |
| DC-11 | `ExportScopeSummary` | Reporting/export (SUR-05) | `FR-27`, `FR-30`, `AC-UI-08` |
| DC-12 | `AuditEntryRow` | Audit review (SUR-05) | `FR-29`, `FR-30`, `FR-32` |

---

## 2. Session and QR components (Lecturer)

### 2.1 `QrDisplayPanel` (DC-01)

Projection-friendly QR surface for the classroom. Trace: `FR-14`, `AC-UI-06`.

| Aspect | Specification |
| --- | --- |
| Layout | Full-width card ([cards.md](./design-system/cards.md)) with thick `2px`–`3px` border and hard shadow; QR occupies ≥ 60% of viewport height in projection mode |
| Header content | Section code, session name, `StatusBadge` for session state, and countdown (`QrCountdownRing`) |
| QR canvas | High-contrast black-on-white module; never apply radius, gradients, or shadow to the QR modules themselves |
| Refresh behavior | QR image swaps automatically before the 30-second TTL expires (`FR-11`); a brief motion-safe crossfade indicates rotation without flashing |
| States | `Open` (QR visible + live countdown), `Closed`/`Cancelled` (QR hidden, replaced by locked state message), token-fetch error (inline `FeedbackAlert`) |
| Data source | `GET /v1/class-sessions/{sessionId}/qr/current` per [05-api-design.md](../technical/05-api-design.md) §4.4 |

Accessibility: the panel exposes a text alternative describing session state and a manual "refresh QR" control for lecturers who need to force rotation; motion respects reduced-motion preferences.

### 2.2 `QrCountdownRing` (DC-02)

Circular TTL indicator paired with `QrDisplayPanel`. Trace: `FR-11`, `FR-12`, `AC-02`.

- Circular/pill geometry is an explicit allowed exception to the `0px` radius default (see [radius.md](./design-system/radius.md)).
- Depletes over the 30-second token lifetime; transitions to brand color when a fresh token is issued.
- Uses warning token family in the final ~5 seconds to signal imminent rotation.
- Provides a numeric seconds-remaining label for users who cannot perceive the ring animation.

### 2.3 `SessionControlBar` (DC-03)

Primary action bar for opening/closing attendance. Trace: `FR-07`, `FR-08`, `FR-10`.

| Region | Content |
| --- | --- |
| Left | Session identity: section code, room, scheduled time, current `StatusBadge` |
| Right | State-appropriate primary action: **Open attendance** (`Scheduled`), **Close attendance** (`Open`), disabled/hidden for `Closed`/`Cancelled` |

Rules:

- The primary CTA is a single unambiguous action per [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md) `FR-UI-01`.
- **Close attendance** routes through `ConfirmActionModal` because it is high-impact and finalizes `Absent` records on the server (`FR-09`, [buttons.md](./design-system/buttons.md), [modals.md](./design-system/modals.md)).
- Invalid transitions (e.g. open on a `Cancelled` session) never render as enabled controls; server rejection maps to `InvalidSessionTransition` and surfaces a danger `FeedbackAlert`.
- Actions map to `POST /v1/class-sessions/{sessionId}/open` and `/close`.

---

## 3. Student check-in components

### 3.1 `CheckInResultScreen` (DC-04)

The single decisive outcome surface after a check-in attempt. Trace: `FR-16`, `FR-22`, `FR-23`, `AC-UI-02`, `AC-UI-03`.

Mobile-first, one screen, minimal navigation. Renders exactly one of the outcome states below, driven by the `outcome`/`error.code` from `POST /v1/check-ins`.

| State | Outcome code | Visual treatment | Copy intent (vi-VN) |
| --- | --- | --- | --- |
| Success — Present | `Success` → `Present` | Success token family, large check icon, timestamp | "Điểm danh thành công — Có mặt" + time |
| Success — Late | `Success` → `Late` | Warning token family, timestamp | "Điểm danh thành công — Đi trễ" + time |
| Expired QR | `ExpiredQr` | Danger alert + retry CTA | "Mã QR đã hết hạn. Vui lòng quét mã mới." |
| Not enrolled | `NotEnrolled` | Danger alert, no retry | "Bạn không thuộc lớp học phần này." |
| Duplicate | `DuplicateCheckIn` | Neutral/info alert | "Bạn đã điểm danh buổi học này rồi." |
| Session not open / closed | `SessionNotOpen`, `SessionClosed` | Danger alert | "Buổi học chưa mở / đã đóng điểm danh." |
| GPS outcomes | `GpsRequired`, `GpsDisabled`, `OutOfRadius`, `LowAccuracy` | Warning/danger alert + guidance | see `GpsPermissionPrompt` recovery copy |
| Unauthenticated | `Unauthenticated` | Redirect to login, return after success | handled by auth gate (`FR-15`) |

Requirements:

- Every failure state includes **reason + next action** (`FR-UI-03`, `AC-UI-02`); no dead-end error.
- Uses [alerts.md](./design-system/alerts.md) variants mapped to reason semantics; success uses [cards.md](./design-system/cards.md) with success tokens.
- Error copy aligns with backend reason-code semantics (`BR-UI-08`, `FR-22`).
- Touch targets meet mobile sizing minimums (`NFR-UI-11`).

### 3.2 `GpsPermissionPrompt` (DC-05)

Requests browser geolocation only at the check-in moment. Trace: `FR-34`, `FR-35`, `BR-08`, `BR-09`, `BR-10`.

- Explains **why** location is needed before triggering the browser permission prompt (data-minimization posture from [00-project-overview.md](../brds/00-project-overview.md) §3.4).
- Copy communicates **risk reduction**, never absolute anti-spoofing (`BR-08`, and [DESIGN.md](./DESIGN.md) §1.3).
- Recovery guidance per outcome:

| Outcome | Guidance |
| --- | --- |
| `GpsDisabled` (permission denied) | Steps to enable location in the browser, then retry; offer "báo giảng viên" fallback path |
| `OutOfRadius` | Prompt to move closer / confirm correct room; may be flagged for lecturer review |
| `LowAccuracy` | Prompt to retry outdoors or wait for a better fix |

- Location is captured **once per attempt**, not tracked continuously.

---

## 4. Roster and attendance components (Lecturer/Admin)

### 4.1 `LiveRosterPanel` (DC-06)

Realtime roster during an `Open` session. Trace: `FR-19`, `AC-UI-05`.

| Aspect | Specification |
| --- | --- |
| Structure | `DataTable` ([tables.md](./design-system/tables.md)) with count summary chips (`present`, `late`, `pending`, `rejectedAttempts`) sourced from `GET /v1/class-sessions/{sessionId}/attendance` |
| Row content | `IdentityCell` (avatar + student code + name), `AttendanceStatusCell`, latest attempt outcome, per-row correction action |
| Realtime | Updates without full-page reload (`NFR-UI-06`); preserves scroll and selected row while `AttendanceRecorded`/`CheckInAttemptRecorded` events arrive |
| Empty/pending | Explicit "chưa có sinh viên điểm danh" state (`NFR-UI-07`) |
| Rejected attempts | Rejected rows show reason code via `StatusBadge` + tooltip ([tooltips-popovers.md](./design-system/tooltips-popovers.md)) |

### 4.2 `AttendanceStatusCell` (DC-07)

Canonical status renderer reused across roster, reports, and history. Trace: `FR-19`, `FR-23`.

- Wraps `StatusBadge` with the tokenized status palette from [DESIGN.md](./DESIGN.md) §4.3:

| Status | Token family |
| --- | --- |
| `Present`, `Manual Present` | success |
| `Late` | warning |
| `Absent`, rejected outcomes | danger |
| `Excused`, `Pending` | neutral/brand soft |

- Values are restricted to the `attendanceStatus` enum in [05-api-design.md](../technical/05-api-design.md) §3.1; never invent statuses.

### 4.3 `ManualCorrectionDialog` (DC-08)

Modal for lecturer/admin manual fallback. Trace: `FR-20`, `FR-21`, `BR-14`, `BR-15`, `BR-16`, `AC-13`, `AC-14`.

| Field | Behavior |
| --- | --- |
| Target | Read-only student identity and current status |
| New status | Dropdown limited to policy-allowed `attendanceStatus` values ([dropdown.md](./design-system/dropdown.md)) |
| Reason | Required text field when policy mandates (`FR-20`); validation per [08-forms-validation-ux.md](./08-forms-validation-ux.md) |
| Scope guard | Lecturer edits outside assigned section are not offered; server denial `OutOfScope` surfaces as danger alert |
| Window guard | Edits outside the manual-edit window show escalation guidance or block per `EditWindowExpired` (`BR-15`) |
| Confirmation | Built on `ConfirmActionModal`; on save, calls `PATCH /v1/class-sessions/{sessionId}/attendance/{studentUserId}` and shows post-action feedback |

Every accepted correction writes an audit entry (old value, new value, actor, reason) — surfaced later via `AuditEntryRow`.

---

## 5. Policy, history, export, and audit components

### 5.1 `PolicyResolutionSummary` (DC-09)

Read-only panel showing the **effective** policy for a section/session. Trace: `FR-24`, `FR-25`.

- Uses [accordion.md](./design-system/accordion.md) for progressive disclosure of present window, late window, auto-close rule, absence threshold, excused handling, manual-edit window, GPS required flag, and GPS radius.
- Shows the resolution precedence (section → course → faculty → institution) so admins understand which level supplied each value.

### 5.2 `AttendanceHistoryList` (DC-10)

Student's personal attendance history. Trace: `FR-37`.

- Grouped by class section; each row uses `AttendanceStatusCell`, check-in timestamp, and method (`QR`, `Manual`, `Admin Correction`).
- Strictly self-scoped: no other students' records, no institution-wide export affordance (`PRM-03`).
- Mobile-first list layout ([lists.md](./design-system/lists.md)).

### 5.3 `ExportScopeSummary` (DC-11)

Scope confirmation shown before an export executes. Trace: `FR-27`, `FR-30`, `AC-UI-08`.

- Displays the active scope (term, section, status filters) and role-derived data boundary **before** triggering `POST /v1/exports/attendance`.
- Reinforces that export is role-scoped (`BR-18`) and produces an audit entry (`FR-30`).

### 5.4 `AuditEntryRow` (DC-12)

Row renderer for audit/evidence review. Trace: `FR-29`, `FR-30`, `FR-32`.

- Displays actor, action type, target (student/session), old value → new value, reason, and timestamp.
- Read-only; no mutation affordances for `SystemAuditor` (`PRM-05`).
- Collapsible detail via [accordion.md](./design-system/accordion.md) for full context.

---

## 6. Cross-cutting component rules

### 6.1 State coverage

Per [DESIGN.md](./DESIGN.md) §2.2 and [03-design-system-basics.md](./03-design-system-basics.md) §3.2, every interactive domain component implements **default, hover, focus, disabled**; async components add **loading** and **error** treatment.

### 6.2 Permission-aware rendering

Actions are gated by role scope from [01-roles-permissions.md](../technical/01-roles-permissions.md). Unauthorized actions are hidden or disabled, never shown as active (`NFR-UI-03`, `AC-UI-09`); denied requests surface explicit feedback without data leakage.

### 6.3 Localization

Student-facing copy is concise Vietnamese (`vi-VN`); technical identifiers stay in English. Error text aligns with backend reason codes (`BR-UI-07`, `BR-UI-08`).

### 6.4 Traceability

| Component concern | FR | BR | AC |
| --- | --- | --- | --- |
| QR rotation and projection clarity | `FR-11`, `FR-14` | `BR-03`, `BR-04` | `AC-02`, `AC-UI-06` |
| Check-in outcome recoverability | `FR-16`, `FR-22`, `FR-23` | `BR-05` to `BR-12` | `AC-UI-02`, `AC-UI-03` |
| GPS risk-reduction UX | `FR-34`, `FR-35` | `BR-08`, `BR-09`, `BR-10` | `AC-11` |
| Manual fallback governance | `FR-20`, `FR-21` | `BR-14` to `BR-16` | `AC-13`, `AC-14` |
| Export/audit scope safety | `FR-27`, `FR-30`, `FR-32` | `BR-18`, `BR-19` | `AC-UI-08`, `AC-UI-09` |

---

## 7. Future consideration

- Per-student challenge-token confirmation UI after QR scan (post-MVP anti-fraud).
- Rich cross-term analytics widgets for attendance trends.
- Dispute-investigation workbench composing `AuditEntryRow` with linked attempt evidence.
