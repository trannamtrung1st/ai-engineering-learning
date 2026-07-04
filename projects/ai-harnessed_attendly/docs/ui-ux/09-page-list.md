# Attendly — Page List

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [01-design-overview.md](./01-design-overview.md) · [05-common-ui-components.md](./05-common-ui-components.md) · [06-app-layout-components.md](./06-app-layout-components.md) · [07-domain-specific-components.md](./07-domain-specific-components.md) · [08-forms-validation-ux.md](./08-forms-validation-ux.md) · [10-user-flows.md](./10-user-flows.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../technical/01-roles-permissions.md](../technical/01-roles-permissions.md) · [../technical/05-api-design.md](../technical/05-api-design.md)

## 1. Purpose and scope

This document is the **canonical page/route inventory** for Attendly MVP. Each entry defines route intent, primary actor(s), role scope, primary action, key states, backing API, and domain components. §2 documents each role's **home / landing hub** and the **navigation entry points** that start user flows. The per-route **search / filter / sort / pagination matrix** in §8 is the source that [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) §0 derives from.

### 1.1 Conventions

- Route groups map to the surfaces in [DESIGN.md](./DESIGN.md) §3.1 (SUR-01 … SUR-05).
- Every page has one unambiguous primary action (`FR-UI-01`) and required empty/loading/error states for listings (`NFR-UI-07`).
- Access is gated by RBAC from [01-roles-permissions.md](../technical/01-roles-permissions.md); unauthorized routes present explicit permission feedback without data leakage (`AC-UI-09`).
- Student routes use a minimal mobile-first shell; staff routes use the persistent app shell from [06-app-layout-components.md](./06-app-layout-components.md).
- Each role has a **home hub** (default post-login landing) reachable from the persistent nav surface on every authenticated page.

### 1.2 Route group overview

| Group | Route prefix | Primary actors | Surface | Home hub |
| --- | --- | --- | --- | --- |
| Auth & entry | `/login`, `/check-in` entry | All / Student | — | — |
| Student | `/check-in`, `/me/*` | Student | SUR-01 | `/check-in` (PG-02) |
| Lecturer | `/lecturer/*` | Lecturer | SUR-02, SUR-03 | `/lecturer/sessions` (PG-04) |
| Admin setup | `/admin/*` | AcademicAdmin, DepartmentAdmin | SUR-04 | `/admin/terms` (PG-07) |
| Reporting & audit | `/reports/*`, `/audit/*` | Lecturer/Admin/Auditor | SUR-05 | `/reports/attendance` (PG-13) or `/audit/logs` (PG-15) by role |

---

## 2. Home and navigation

Each authenticated role lands on a **home hub** after login (or after `returnUrl` handling). The home hub is the navigation anchor for that role's experience — reachable from every other page via the persistent nav surface (`SidebarNav` or `StudentLayout` mobile shell) per [06-app-layout-components.md](./06-app-layout-components.md).

### 2.1 Home / landing hubs per role

Post-login redirect targets align with [01-roles-permissions.md](../technical/01-roles-permissions.md) and [10-user-flows.md](./10-user-flows.md) FLOW-14. When `returnUrl` is present, prefer it over the defaults below.

| Role | Home route | Page | Layout | Minimum hub content | Primary flows |
| --- | --- | --- | --- | --- | --- |
| Student | `/check-in` | PG-02 | `LAY-01` / `StudentLayout` | In-app QR scanner; recent attendance summary | [FLOW-01](./10-user-flows.md#21-flow-01--student-qr-check-in-happy-path), [FLOW-04](./10-user-flows.md#24-flow-04--student-attendance-history) |
| Lecturer | `/lecturer/sessions` | PG-04 | `LAY-02` / `StaffLayout` | Today's and upcoming scheduled sessions list | [FLOW-05](./10-user-flows.md#31-flow-05--open-session-and-display-qr), [FLOW-06](./10-user-flows.md#32-flow-06--monitor-live-roster) |
| DepartmentAdmin | `/lecturer/sessions` | PG-04 | `LAY-02` / `StaffLayout` | Scoped session list (department) | FLOW-05, [FLOW-12](./10-user-flows.md#44-flow-12--attendance-report-and-export) |
| AcademicAdmin | `/admin/terms` | PG-07 | `LAY-03` / `AdminLayout` | Active term overview; quick links to sections and policies | [FLOW-09](./10-user-flows.md#41-flow-09--academic-structure-setup), [FLOW-11](./10-user-flows.md#43-flow-11--attendance-policy-configuration) |
| ITAdmin | `/audit/logs` | PG-15 | `LAY-04` / `StaffLayout` | Recent audit log entries with status indicators | [FLOW-13](./10-user-flows.md#45-flow-13--audit-log-review) |
| SystemAuditor | `/audit/logs` | PG-15 | `LAY-04` / `StaffLayout` | Recent audit log entries (read-only) | FLOW-13 |

Home hubs are **not** listing-matrix routes unless they also appear in §8 (e.g. PG-04, PG-07, PG-15). They must still expose at least one live data surface (summary count, recent list, or status overview) — not an empty shell or redirect loop.

### 2.2 Navigation entry points

The persistent nav surface lists only routes the current role may access (`AC-UI-09`). Each item is an entry point into one or more user flows from [10-user-flows.md](./10-user-flows.md). The **home item** is always the first nav entry for that role.

#### Student — `StudentLayout` mobile shell

| Nav label (vi-VN) | Route | Page | Starts flow(s) |
| --- | --- | --- | --- |
| Trang chủ | `/check-in` | PG-02 | FLOW-01, FLOW-02, FLOW-03 |
| Lịch sử điểm danh | `/me/attendance` | PG-03 | FLOW-04 |

#### Lecturer / DepartmentAdmin — `StaffLayout` `SidebarNav`

| Nav label (vi-VN) | Route | Page | Starts flow(s) | Role gate |
| --- | --- | --- | --- | --- |
| Phiên học *(home)* | `/lecturer/sessions` | PG-04 | FLOW-05 → PG-05, PG-06 | Lecturer, DepartmentAdmin |
| Báo cáo điểm danh | `/reports/attendance` | PG-13 | FLOW-12 → PG-14 export dialog | Lecturer (scoped), DepartmentAdmin, AcademicAdmin, SystemAuditor |
| Nhật ký kiểm toán | `/audit/logs` | PG-15 | FLOW-13 | AcademicAdmin, ITAdmin, SystemAuditor |

Session detail routes (`PG-05`, `PG-06`) are reached from PG-04 row actions, not as top-level nav items. Deep routes require breadcrumb orientation via `TopContextHeader` (`FR-LAY-05`).

#### AcademicAdmin — `AdminLayout` `SidebarNav`

| Nav label (vi-VN) | Route | Page | Starts flow(s) |
| --- | --- | --- | --- |
| Học kỳ *(home)* | `/admin/terms` | PG-07 | FLOW-09 |
| Khóa học | `/admin/courses` | PG-08 | FLOW-09 |
| Lớp học phần | `/admin/class-sections` | PG-09 | FLOW-09 → PG-10 enrollment |
| Phòng học | `/admin/rooms` | PG-11 | FLOW-09 |
| Chính sách điểm danh | `/admin/policies` | PG-12 | FLOW-11 |

Enrollment import (PG-10) is a secondary route from PG-09 row actions, not a top-level nav item.

#### ITAdmin / SystemAuditor — `StaffLayout` `SidebarNav`

| Nav label (vi-VN) | Route | Page | Starts flow(s) |
| --- | --- | --- | --- |
| Nhật ký kiểm toán *(home)* | `/audit/logs` | PG-15 | FLOW-13 |

Navigation rules:

- **Home link always visible** — first nav item or linked product logo on every authenticated page.
- **Logout always visible** — **Đăng xuất** control in sidebar footer (staff layouts) or student shell header/account menu on every authenticated page (`FR-38`).
- **RBAC omission** — nav items for forbidden routes are absent from rendered output, not disabled (`AC-UI-09`).
- **No dead ends** — detail, modal, and outcome pages provide breadcrumb, close, or home recovery per [06-app-layout-components.md](./06-app-layout-components.md) §6.

---

## 3. Auth and entry pages

### PG-01 — Login

| Field | Value |
| --- | --- |
| Route | `/login` |
| Actor | All roles |
| Primary action | Sign in |
| Key states | default, submitting, error (locked/throttled) |
| Form | FRM-01 ([08-forms-validation-ux.md](./08-forms-validation-ux.md) §4.1) |
| API | `POST /v1/auth/login` |
| Trace | `FR-15`, `FR-36` |

Voluntary logout from any authenticated surface follows FLOW-15 (`FR-38`); user returns here without `returnUrl`.

### PG-02 — Check-in entry (in-app scanner)

| Field | Value |
| --- | --- |
| Route | `/check-in` (`?token=` query param is harness/test-only; not a documented student entry path) |
| Actor | Student |
| Primary action | Scan QR (in-app camera), then submit check-in |
| Key states | authenticating (redirect to `/login`), `camera-prompt`, `scanning`, `token-captured`, GPS prompt, submitting, result |
| Components | `QrScannerPanel` (DC-13), `GpsPermissionPrompt`, `CheckInResultScreen` (DC-04/DC-05) |
| API | `POST /v1/check-ins` |
| Trace | `FR-16`, `FR-17`, `FR-18`, `FR-34`; `BR-05` to `BR-12` |

Unauthenticated access redirects to PG-01 and returns here after login (`FR-15`).

---

## 4. Student pages

### PG-03 — My attendance history

| Field | Value |
| --- | --- |
| Route | `/me/attendance` |
| Actor | Student (self-only) |
| Primary action | View records; filter by section/term |
| Key states | empty, loading, list, error |
| Component | `AttendanceHistoryList` (DC-10) |
| API | `GET /v1/reports/attendance` (self-scoped) |
| Trace | `FR-37`; `PRM-03` |

Strictly self-scoped; no export affordance, no other students' data.

---

## 5. Lecturer pages

### PG-04 — Lecturer session list

| Field | Value |
| --- | --- |
| Route | `/lecturer/sessions` |
| Actor | Lecturer (assigned sections) |
| Primary action | Open a scheduled session |
| Key states | empty, loading, list (`Scheduled`/`Open`/`Closed`/`Cancelled` badges), error |
| Components | `SessionControlBar` (DC-03), `TableToolbar`, `DataTable` |
| API | `GET /v1/class-sessions?classSectionId=&date=&state=` |
| Trace | `FR-06`, `FR-10`; `AC-01` |

### PG-05 — Session control (QR display)

| Field | Value |
| --- | --- |
| Route | `/lecturer/sessions/{sessionId}` |
| Actor | Lecturer (assigned) |
| Primary action | Open / Close attendance |
| Key states | `Scheduled`, `Open` (rotating QR + countdown), `Closed`, `Cancelled`, token-fetch error |
| Components | `QrDisplayPanel`, `QrCountdownRing`, `SessionControlBar` (DC-01/02/03) |
| API | `POST /open`, `POST /close`, `GET /qr/current` |
| Trace | `FR-07`, `FR-08`, `FR-11`, `FR-14`; `AC-02`, `AC-UI-06` |

Close routes through `ConfirmActionModal` and finalizes `Absent` records (`FR-09`).

### PG-06 — Live roster

| Field | Value |
| --- | --- |
| Route | `/lecturer/sessions/{sessionId}/roster` |
| Actor | Lecturer (assigned) |
| Primary action | Manual correction on a student row |
| Key states | live updating, empty/pending, rejected-attempt rows, error |
| Components | `LiveRosterPanel`, `AttendanceStatusCell`, `ManualCorrectionDialog` (DC-06/07/08) |
| API | `GET /v1/class-sessions/{id}/attendance`, `PATCH .../attendance/{studentUserId}` |
| Trace | `FR-19`, `FR-20`; `BR-14`; `AC-13`, `AC-UI-05` |

Realtime updates preserve scroll/selection (`NFR-UI-06`).

---

## 6. Admin setup pages

Admin management pages are the primary listing surfaces and all use `TableToolbar` + `DataTable` per [05-common-ui-components.md](./05-common-ui-components.md).

### PG-07 — Terms

| Field | Value |
| --- | --- |
| Route | `/admin/terms` |
| Actor | AcademicAdmin |
| Primary action | Create term |
| Form | FRM-02 |
| API | `GET`/`POST /v1/terms` |
| Trace | `FR-01` |

### PG-08 — Courses

| Field | Value |
| --- | --- |
| Route | `/admin/courses` |
| Actor | AcademicAdmin |
| Primary action | Create course |
| Form | FRM-03 |
| API | `GET`/`POST /v1/courses` |
| Trace | `FR-02` |

### PG-09 — Class sections

| Field | Value |
| --- | --- |
| Route | `/admin/class-sections` |
| Actor | AcademicAdmin, DepartmentAdmin (scoped), Lecturer (read) |
| Primary action | Create section |
| Form | FRM-04 |
| API | `GET`/`POST /v1/class-sections` |
| Trace | `FR-03`, `FR-06`; `BR-19` |

### PG-10 — Enrollment import

| Field | Value |
| --- | --- |
| Route | `/admin/class-sections/{id}/enrollments` |
| Actor | AcademicAdmin, DepartmentAdmin (scoped) |
| Primary action | Import CSV |
| Form | FRM-06 (row-level error reporting) |
| API | `POST /v1/enrollments/import` |
| Trace | `FR-04`; `BR-06` |

### PG-11 — Rooms and locations

| Field | Value |
| --- | --- |
| Route | `/admin/rooms` |
| Actor | AcademicAdmin |
| Primary action | Create room |
| Form | FRM-05 |
| API | `GET`/`POST /v1/rooms` |
| Trace | `FR-05` |

### PG-12 — Attendance policies

| Field | Value |
| --- | --- |
| Route | `/admin/policies` |
| Actor | AcademicAdmin |
| Primary action | Configure policy |
| Form | FRM-07; `PolicyResolutionSummary` (DC-09) preview |
| API | policy config endpoints |
| Trace | `FR-24`, `FR-25` |

---

## 7. Reporting and audit pages

### PG-13 — Attendance reports

| Field | Value |
| --- | --- |
| Route | `/reports/attendance` |
| Actor | Lecturer, DepartmentAdmin, AcademicAdmin, SystemAuditor (read-only) |
| Primary action | Filter and view report |
| Components | `TableToolbar`, `DataTable`, `AttendanceStatusCell` |
| API | `GET /v1/reports/attendance` |
| Trace | `FR-28`; `BR-19` |

### PG-14 — Export

| Field | Value |
| --- | --- |
| Route | `/reports/attendance/export` (dialog on PG-13) |
| Actor | Lecturer (scoped), DepartmentAdmin (scoped), AcademicAdmin |
| Primary action | Create CSV export |
| Component | `ExportScopeSummary` (DC-11) before execution |
| API | `POST /v1/exports/attendance` |
| Trace | `FR-27`, `FR-30`; `BR-18`; `AC-UI-08` |

### PG-15 — Audit log review

| Field | Value |
| --- | --- |
| Route | `/audit/logs` |
| Actor | AcademicAdmin, ITAdmin (technical), SystemAuditor (read-only) |
| Primary action | Search and inspect audit entries |
| Components | `TableToolbar`, `DataTable`, `AuditEntryRow` (DC-12) |
| API | `GET /v1/audit-logs` |
| Trace | `FR-29`, `FR-30`, `FR-32`; `BR-22` |

---

## 8. Listing search / filter / sort / pagination matrix

This matrix is the **source of truth** for listing behavior; [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) §0 derives its per-route matrix from this table. Query parameters align with [05-api-design.md](../technical/05-api-design.md) §2.5 (`page`, `pageSize`, `sortBy`, `sortOrder`, `search`, `from`, `to`). All filters resolve **after** role-scope authorization (`BR-18`, `BR-19`).

| Page | Route | Search | Filters | Sort fields | Pagination |
| --- | --- | --- | --- | --- | --- |
| PG-03 My attendance | `/me/attendance` | — | term, section, status | date (desc default) | yes (`page`/`pageSize`) |
| PG-04 Lecturer sessions | `/lecturer/sessions` | section/session text | date, state | start time, state | yes |
| PG-06 Live roster | `/lecturer/sessions/{id}/roster` | student name/code | status, attempt outcome | status, check-in time | virtualized / no server paging (single session) |
| PG-07 Terms | `/admin/terms` | term name/code | active flag | start date, name | yes |
| PG-08 Courses | `/admin/courses` | course name/code | faculty | code, name | yes |
| PG-09 Class sections | `/admin/class-sections` | section code | term, course, lecturer | section code, term | yes |
| PG-10 Enrollment import | `/admin/.../enrollments` | student name/code | enrollment status | student code | yes |
| PG-11 Rooms | `/admin/rooms` | room/building name | building, GPS-enabled | name, building | yes |
| PG-12 Policies | `/admin/policies` | scope name | scope level | scope level, updated | yes |
| PG-13 Reports | `/reports/attendance` | student name/code | term, section, course, lecturer, status, date range (`from`/`to`) | date, status, section | yes |
| PG-15 Audit logs | `/audit/logs` | actor / target | actor, target type, action type, date range (`from`/`to`) | timestamp (desc default) | yes |

Matrix rules:

- **Search** is normalized text within authorized scope; empty search returns the full scoped set.
- **Filters** show active-state chips with clear-all (`FR-TTB-02`); toolbar state syncs with route query params (`FR-TTB-05`).
- **Sort** state is visible and reversible (`FR-TTB-03`); `sortBy` uses allow-listed server fields only.
- **Pagination** uses server pagination (`pageSize` default `25`, max `100`); pagination metadata never exposes cross-scope counts.
- Every listing has explicit **empty**, **no-result**, **loading**, and **error** states (`NFR-UI-07`).

---

## 9. Page-to-requirement traceability

| Page group | FR | BR | AC / NFR |
| --- | --- | --- | --- |
| Home & navigation | `FR-15`, `FR-36`, `FR-38` | `BR-19`, `BR-24` | `AC-UI-01`, `AC-UI-09`, `AC-26`, `NFR-LAY-01` to `NFR-LAY-06` |
| Auth & check-in | `FR-15`, `FR-16`, `FR-36`, `FR-38` | `BR-05` to `BR-12`, `BR-24` | `AC-UI-01` to `AC-UI-03`, `AC-06`, `AC-26` |
| Lecturer session/roster | `FR-07`, `FR-08`, `FR-11`, `FR-14`, `FR-19`, `FR-20` | `BR-01` to `BR-04`, `BR-14` | `AC-01`, `AC-02`, `AC-13`, `AC-UI-04` to `AC-UI-06` |
| Admin setup | `FR-01` to `FR-06`, `FR-24`, `FR-25` | `BR-06`, `BR-19` | `AC-UI-07` |
| Reporting/export | `FR-27`, `FR-28`, `FR-30` | `BR-18`, `BR-19` | `AC-UI-08`, `AC-UI-09` |
| Audit review | `FR-29`, `FR-30`, `FR-32` | `BR-22` | `NFR-UI-03` |

---

## 10. Future consideration

- Cross-term analytics dashboard route for academic leadership.
- Department-admin exception queue route for pending disputes.
- Saved filter presets per role on listing routes.
