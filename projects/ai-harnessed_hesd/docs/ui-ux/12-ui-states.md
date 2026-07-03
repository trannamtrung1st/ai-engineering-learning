# Attendly — UI States

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [09-page-list.md](./09-page-list.md) · [10-user-flows.md](./10-user-flows.md) · [11-wireframes.md](./11-wireframes.md) · [07-domain-specific-components.md](./07-domain-specific-components.md) · [../brds/05-state-machine.md](../brds/05-state-machine.md) · [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md)

## 1. Purpose and scope

This document defines **UI state models** for Attendly MVP: domain-driven states, visual treatment, component mapping, and transition rules. States align with canonical names from [05-state-machine.md](../brds/05-state-machine.md) and API enums in [05-api-design.md](../technical/05-api-design.md). Every interactive control also implements interaction states (default, hover, focus, disabled, loading, error) per [03-design-system-basics.md](./03-design-system-basics.md) §3.2.

### 1.1 State taxonomy

| Category | Scope | Examples |
| --- | --- | --- |
| Domain state | Business entity lifecycle | Session `Open`, attendance `Present` |
| Outcome state | Single check-in attempt result | `ExpiredQr`, `DuplicateCheckIn` |
| Page state | Route-level UX mode | `loading`, `empty`, `error` |
| Control state | Component interaction | `hover`, `focus`, `disabled` |
| Realtime state | Live data freshness | `syncing`, `stale`, `connected` |

---

## 2. Session attendance window states

Canonical `ClassSession` states govern lecturer surfaces (SUR-02, SUR-03) and student check-in eligibility.

### 2.1 State matrix

| State | Meaning | Check-in accepted | QR visible | Primary lecturer CTA | Badge token |
| --- | --- | --- | --- | --- | --- |
| `Scheduled` | Timetable entry; window not open | No | No | **Open attendance** | neutral |
| `Open` | Active attendance window | Yes | Yes (rotating) | **Close attendance** | success/brand |
| `Closed` | Window ended; roster frozen | No | No | — (manual edit only) | neutral/dark |
| `Cancelled` | Session abandoned | No | No | — | danger/neutral |

Trace: `FR-UI-02`, `BR-01`, `BR-02`, `AC-01`, `AC-05`.

### 2.2 UI transition rules

| From | To | Trigger | UI feedback |
| --- | --- | --- | --- |
| `Scheduled` | `Open` | Lecturer taps open | Optimistic badge update; QR panel animates in; countdown starts (`AC-02`) |
| `Open` | `Closed` | Lecturer confirms close or auto-close | `ConfirmActionModal` → badge locks; QR hidden; roster summary updates (`AC-12`) |
| `Scheduled` | `Cancelled` | Admin/lecturer cancel | QR never shown; open CTA removed |
| Invalid | — | e.g. open on `Closed` | `InvalidSessionTransition` danger alert; control stays disabled |

MVP does not support `Closed` → `Open` reopening; manual corrections handle exceptions (`BR-14`).

### 2.3 Component mapping (SUR-02)

| Component | `Scheduled` | `Open` | `Closed` | `Cancelled` |
| --- | --- | --- | --- | --- |
| `SessionControlBar` (DC-03) | Open CTA enabled | Close CTA enabled | CTAs hidden | CTAs hidden |
| `QrDisplayPanel` (DC-01) | Locked message | QR + countdown | Locked message | Cancelled message |
| `QrCountdownRing` (DC-02) | Hidden | Active 30 s cycle | Hidden | Hidden |
| Page header `StatusBadge` | `Scheduled` chip | `Open` chip (emphasized) | `Closed` chip | `Cancelled` chip |

---

## 3. QR token states

`QRSessionToken` states are distinct from session states; they drive student check-in feedback.

| Token state | UI on student (PG-02) | Lecturer display |
| --- | --- | --- |
| `Valid` | Proceed to validation / success path | QR rendered; countdown active |
| `Expired` | `CheckInResultScreen` → `ExpiredQr` + retry CTA | Auto-refresh to new token |
| `Invalid` | Danger alert; scan correct QR | Error alert if fetch fails |

Trace: `FR-11`–`FR-13`, `BR-03`, `BR-04`, `AC-03`, `AC-04`.

**Multi-use within TTL:** Multiple students may submit with the same `Valid` token; UI does not show "token already used" (`AC-03`).

---

## 4. Attendance record states

Per-student roster outcomes rendered via `AttendanceStatusCell` (DC-07) and `StatusBadge`.

### 4.1 Status palette

| Status | Semantic token | Badge variant | Typical context |
| --- | --- | --- | --- |
| `Pending` | neutral/brand soft | neutral | No successful check-in yet |
| `Present` | success | success | QR check-in within present window |
| `Late` | warning | warning | QR check-in within late window |
| `Absent` | danger | danger | Auto-absent on close or unresolved |
| `Excused` | neutral | neutral/outline | Policy-approved absence |
| `Manual Present` | success | success (distinct label) | Lecturer/admin correction |

Trace: `FR-23`, `FR-09`, `BR-11`–`BR-13`, `AC-11`, `AC-12`.

### 4.2 Roster grouping (PG-06)

`LiveRosterPanel` groups rows for scan speed:

| Group | Included statuses | UI treatment |
| --- | --- | --- |
| Checked in | `Present`, `Late`, `Manual Present` | Default row; success/warning badge |
| Pending | `Pending` | Muted row; pending badge |
| Rejected attempts | Latest failed attempt per student | Danger/warning badge + reason tooltip |
| Absent (post-close) | `Absent` | Danger badge after session `Closed` |

---

## 5. Check-in outcome states

`CheckInResultScreen` (DC-04) renders exactly one outcome per submission.

### 5.1 Outcome state catalog

| Outcome code | Page state ID | Alert variant | Retry allowed | Copy intent (vi-VN) |
| --- | --- | --- | --- | --- |
| `Success` → `Present` | `success-present` | success card | No | Điểm danh thành công — Có mặt |
| `Success` → `Late` | `success-late` | warning card | No | Điểm danh thành công — Đi trễ |
| `ExpiredQr` | `failure-expired-qr` | danger | Yes (re-scan) | Mã QR đã hết hạn |
| `SessionNotOpen` | `failure-not-open` | danger | No | Buổi học chưa mở điểm danh |
| `SessionClosed` | `failure-closed` | danger | No | Buổi học đã đóng điểm danh |
| `NotEnrolled` | `failure-not-enrolled` | danger | No | Không thuộc lớp học phần |
| `DuplicateCheckIn` | `failure-duplicate` | info | No | Đã điểm danh buổi này |
| `GpsDisabled` | `failure-gps-denied` | warning | Yes (after enable) | Cần quyền vị trí |
| `OutOfRadius` | `failure-out-of-radius` | warning | Yes / manual | Ngoài phạm vi lớp |
| `LowAccuracy` | `failure-low-accuracy` | warning | Yes | Độ chính xác GPS thấp |
| `Unauthenticated` | `authenticating` | — | Redirect login | Đăng nhập để tiếp tục |

Trace: `FR-22`, `BR-23`, `AC-18`, `AC-UI-02`, `FR-UI-03`.

### 5.2 Submission lifecycle (PG-02)

```
loading → (gps-prompt?) → submitting → [outcome state]
```

- `loading`: resolve token and session context.
- `gps-prompt`: only when policy requires and permission not yet granted.
- `submitting`: disable duplicate submit; show spinner.
- Outcome: full-screen `CheckInResultScreen`; no ambiguous intermediate states.

---

## 6. Page-level states (listings and forms)

All listing routes (PG-03, PG-04, PG-06, PG-07–PG-15) require four page states (`NFR-UI-07`).

### 6.1 Listing page state model

| State ID | When shown | Visual pattern | Recovery action |
| --- | --- | --- | --- |
| `loading` | Initial fetch or filter change | Skeleton rows or table shimmer | — |
| `empty` | Zero records in authorized scope | Illustration + "Chưa có dữ liệu" + create CTA if permitted | Link to setup flow |
| `no-results` | Filters/search yield zero matches | "Không tìm thấy kết quả" + clear filters | Clear-all chip action |
| `error` | API failure or timeout | `FeedbackAlert` danger + retry | `[ Thử lại ]` |
| `list` | Data returned | `DataTable` + pagination | — |

### 6.2 Form page states

| State ID | When shown | Behavior |
| --- | --- | --- |
| `default` | Form ready | Fields editable per role |
| `submitting` | POST/PATCH in flight | Disable submit; inline spinner |
| `success` | Save accepted | Toast or inline success; optional redirect |
| `validation-error` | Client or 400 response | Inline field errors + summary alert |
| `permission-denied` | 403 / out of scope | Form read-only or hidden; scope alert (`AC-UI-09`) |

Reference: [08-forms-validation-ux.md](./08-forms-validation-ux.md) §2–3.

---

## 7. Realtime and async states

### 7.1 Live roster (PG-06)

| State | Indicator | Behavior |
| --- | --- | --- |
| `connected` | Subtle live dot in header | Rows update in place (`NFR-UI-06`) |
| `syncing` | Brief row highlight on change | Preserve scroll position and selection |
| `stale` | "Cập nhật lúc HH:MM" timestamp | Manual refresh affordance |
| `disconnected` | Warning banner | Auto-reconnect; fallback poll every 10 s |

### 7.2 QR token fetch (PG-05)

| State | UI |
| --- | --- |
| `fetching` | Previous QR remains until replacement ready (no blank flash) |
| `ready` | New QR crossfades in; countdown resets |
| `error` | Inline `FeedbackAlert` + manual refresh button |

---

## 8. Permission and scope states

| State ID | Trigger | UI treatment |
| --- | --- | --- |
| `authorized` | User has role + scope | Full interactive surface |
| `read-only` | View permission only | Data visible; write controls hidden |
| `hidden` | Route not in role nav | Nav item omitted |
| `denied` | Direct URL without permission | Empty state with "Không có quyền truy cập" — no data leakage (`BR-19`, `AC-16`) |

Export and report surfaces additionally show `ExportScopeSummary` in `preview` state before execution (`AC-UI-08`).

---

## 9. Interaction states (controls)

Per [03-design-system-basics.md](./03-design-system-basics.md) and [DESIGN.md](./DESIGN.md) §2.2.

| Control state | Visual requirement | Applies to |
| --- | --- | --- |
| `default` | Token border and background | All interactive elements |
| `hover` | Hard shadow offset increase | Buttons, rows, toolbar chips |
| `focus` | Visible focus ring (`NFR-UI-08`) | All focusable controls |
| `disabled` | Reduced emphasis; `aria-disabled` | Invalid transitions, out-of-window edits |
| `loading` | Spinner replaces label or inline | Submit, export, token fetch |
| `error` | Danger border on field or alert | Forms, async failures |

Destructive actions (`Close attendance`, manual correction confirm) use `ConfirmActionModal` — modal adds `open` / `confirming` / `closed` sub-states (`BR-UI-06`).

---

## 10. State traceability

| State domain | FR | BR | AC / NFR |
| --- | --- | --- | --- |
| Session window | `FR-07`, `FR-08` | `BR-01`, `BR-02` | `AC-01`, `AC-05`, `FR-UI-02` |
| QR token | `FR-11`–`FR-13` | `BR-03`, `BR-04` | `AC-02`–`AC-04` |
| Attendance status | `FR-09`, `FR-23` | `BR-11`–`BR-13` | `AC-11`, `AC-12` |
| Check-in outcomes | `FR-22` | `BR-23` | `AC-18`, `AC-UI-02`, `AC-UI-03` |
| Listing page states | `FR-28` | — | `NFR-UI-07`, `AC-UI-07` |
| Realtime roster | `FR-19` | — | `NFR-UI-06` |
| Permission scope | `FR-27`, `FR-32` | `BR-18`, `BR-19` | `AC-16`, `AC-UI-09` |

---

## 11. Future consideration

- `Suspicious` check-in flag as first-class roster row state with review queue.
- Session `Paused` state for mid-class interruptions (not in MVP).
- Optimistic UI rollback patterns for failed manual corrections.
- Connection-quality indicator on student check-in for campus network diagnostics.
