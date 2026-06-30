# We Check — UI/UX Foundation

Foundational UX rules, constraints, and patterns for **We Check** MVP. All screens and components must align with this document before feature-specific specs.

**Related documents:** [Design overview](./01-design-overview.md) · [Production quality bar](./00-production-ui-quality-bar.md) · [BRD prompt](../brds/prompt.md) · [Business rules](../brds/04-business-rules.md) · [State machine](../brds/05-state-machine.md)

---

## 1. Foundation

This document establishes cross-cutting UX contracts: canonical terminology, state presentation, permission flows, localization, and traceability to requirements. Feature pages and domain components build on these rules in downstream UI/UX specs.

---

## 2. Canonical Terminology (Vietnamese UI)

Use these user-facing labels consistently. Technical enums in code remain English per [05-state-machine.md](../brds/05-state-machine.md).

### 2.1 Session lifecycle

| State (code) | Vietnamese label | UI treatment |
| --- | --- | --- |
| `Draft` | Nháp | Muted badge; editable |
| `Active` | Đang diễn ra | Green badge; QR and monitor enabled |
| `Closed` | Đã kết thúc | Gray badge; check-in disabled |
| `Cancelled` | Đã hủy | Red outline badge; read-only |

### 2.2 Attendance record

| State (code) | Vietnamese label | Color token |
| --- | --- | --- |
| `Pending` | Chưa điểm danh | `warning` |
| `Present` | Có mặt | `success` |
| `Absent` | Vắng | `danger` |
| `Excused` | Vắng có phép | `info` |
| `Rejected` | Từ chối | `danger` + reason tooltip |

### 2.3 Check-in outcomes

| Outcome (code) | User message (summary) |
| --- | --- |
| `Success` | Điểm danh thành công |
| `ExpiredQr` | Mã QR đã hết hạn, vui lòng quét mã mới ([BR-03](../brds/04-business-rules.md)) |
| `OutOfRadius` | Bạn đang ngoài phạm vi phòng học |
| `DuplicateCheckIn` | Bạn đã điểm danh buổi học này rồi ([BR-04](../brds/04-business-rules.md)) |
| `GpsDisabled` | Vui lòng bật GPS và cấp quyền định vị ([BR-12](../brds/04-business-rules.md)) |
| `Unauthenticated` | Redirect to login |
| `SessionNotActive` | Buổi học chưa mở hoặc đã kết thúc |
| `SpoofSuspected` | Không thể xác minh vị trí; liên hệ giảng viên |

Full strings live in `@wecheck/domain` message catalog ([NFR-17](../brds/07-non-functional-risk.md)).

---

## 3. UX Constraints from Business Rules

| Rule | UX requirement |
| --- | --- |
| [BR-01](../brds/04-business-rules.md) | After attendance window, check-in UI shows closed state; late scans explain `Absent` |
| [BR-03](../brds/04-business-rules.md) | Expired QR shows countdown context (“Mã mới sau X giây”) on instructor display |
| [BR-06](../brds/04-business-rules.md) | Unauthenticated check-in deep link → login → return URL preserved |
| [BR-07](../brds/04-business-rules.md) | “Mở buổi học” disabled with inline error until room GPS set |
| [BR-08](../brds/04-business-rules.md) | Forbidden report access → full-page **403** with Vietnamese explanation |
| [BR-09](../brds/04-business-rules.md) | CSV export control hidden or disabled for non-admin roles |
| [BR-10](../brds/04-business-rules.md) | Manual edit shows **24-hour** window notice; requires reason |
| [BR-12](../brds/04-business-rules.md) | GPS denial → modal with OS-specific enable steps |
| [BR-14](../brds/04-business-rules.md) | Nav items for forbidden routes omitted from chrome — not disabled |
| [BR-15](../brds/04-business-rules.md) | Preflight failure keeps user on scan step; no GPS mount |

---

## 4. Layout and Navigation Foundation

### 4.1 Role-based route trees

| Role | Shell | Default landing |
| --- | --- | --- |
| `Student` | `StudentLayout` — bottom nav or minimal header | `/check-in` or `/history` |
| `Instructor` | `InstructorLayout` — sidebar + top bar | `/sessions` |
| `TrainingOfficeAdmin` | `AdminLayout` — sidebar + top bar | `/admin` hub |

Layout component specs: [06-app-layout-components.md](./06-app-layout-components.md).

### 4.2 Navigation rules

- Maximum **2 levels** of hierarchy in primary nav for MVP.
- Current location always visible (breadcrumb or active nav item).
- **Singleton active indicator:** At most **one** primary nav item (sidebar or bottom nav) shows active styling per layout shell. The active item must reflect the **most specific** matching route — sibling prefix routes must not both appear active ([BR-14a](../brds/04-business-rules.md), [AC-18h](../brds/08-acceptance-mvp-future.md)).
- Logout and user display name in header on all authenticated shells. Display name appears on the UserMenu trigger; full identity (name, email, institutional ID, role) appears inside the dropdown panel ([05-common-ui-components.md](./05-common-ui-components.md) §6.3).
- Student check-in route suppresses distracting nav during active scan.

---

## 5. Interaction Patterns

### 5.1 Forms

- Labels above fields; required fields marked with asterisk and `aria-required`.
- Inline validation on blur; submit blocked until Zod schema passes ([08-forms-validation-ux.md](./08-forms-validation-ux.md) downstream).
- Destructive actions use confirmation dialog with verb in title (“Hủy buổi học”).

### 5.2 Lists and tables

- Default sort: upcoming sessions ascending by start time; attendance roster by name.
- Empty states include primary CTA (“Tạo buổi học”, “Import CSV”).
- Row actions via icon button + `aria-label` in Vietnamese.

### 5.3 Feedback

| Situation | Pattern |
| --- | --- |
| Transient success | Toast, **4 s** auto-dismiss |
| Recoverable error | Toast + retry button |
| Blocking error | Inline alert or modal |
| Long operation | Button loading spinner; disable double-submit |
| Polling refresh | Subtle “Cập nhật lúc HH:mm:ss” timestamp |

### 5.4 Real-time updates (polling)

- QR display: poll token every **5 s** ([FR-06](../brds/03-functional-requirements.md)).
- Live attendance: poll every **5 s** while session `Active` ([FR-15](../brds/03-functional-requirements.md)).
- Show stale indicator if last fetch failed.

---

## 6. Mobile Check-In Foundation

Student check-in ([FR-07](../brds/03-functional-requirements.md), [FR-08](../brds/03-functional-requirements.md)) follows a linear step model:

1. **Context** — session title, room, time window (after preflight pass).
2. **Permissions** — camera and GPS consent with privacy note (GPS not stored after validation per [NFR-12](../brds/07-non-functional-risk.md)).
3. **Scan** — camera viewfinder with QR overlay.
4. **Preflight** — `GET /check-in/tokens/:tokenId/preflight`; inline validating state on scan step; failures stay on scan ([BR-15](../brds/04-business-rules.md)).
5. **GPS capture** — acquire coordinates; **ready** shows check icon without spinner ([AC-08f](../brds/08-acceptance-mvp-future.md)).
6. **Submit** — explicit **Xác nhận điểm danh** tap; spinner only during `submitting`.
7. **Outcome** — result screen with icon, message, and next action.

No optimistic success. Network retry: up to **3** attempts within **30 s**.

---

## 7. Instructor QR Display Foundation

Full-screen layout requirements ([NFR-20](../brds/07-non-functional-risk.md)):

- QR minimum **40%** of viewport width on projector view.
- Countdown timer **≥ 48 px** font size in presentation mode.
- Session title and room in header bar.
- Auto-rotate visual pulse when token refreshes (respect `prefers-reduced-motion`).
- “Thoát toàn màn hình” exits fullscreen without closing session.

---

## 8. Privacy and Consent Copy

GPS consent block (shown before first location request):

> We Check sử dụng vị trí thiết bị một lần để xác minh bạn đang trong phòng học. Tọa độ GPS **không được lưu** sau khi điểm danh thành công.

Camera consent block:

> Camera chỉ dùng để quét mã QR điểm danh. Hình ảnh không được ghi lại hoặc tải lên máy chủ.

Aligns with [NFR-12](../brds/07-non-functional-risk.md) and Vietnam personal data expectations in [07-non-functional-risk.md](../brds/07-non-functional-risk.md).

---

## 9. Accessibility Foundation

- All interactive elements keyboard reachable; visible focus ring (`--focus-ring` token).
- Status not conveyed by color alone — include icon or text label.
- Dialogs: focus trap, `aria-modal`, labelled title.
- Live regions for check-in outcome announcements (`aria-live="polite"`).
- Detailed checklist: [13-accessibility-basics.md](./13-accessibility-basics.md) (downstream).

---

## 10. Traceability Matrix

| Foundation area | FR | NFR | AC |
| --- | --- | --- | --- |
| Terminology / states | FR-05, FR-09 | — | AC-05 |
| Check-in flow | FR-07, FR-08 | NFR-18, NFR-19 | AC-07, AC-08 |
| QR display | FR-06 | NFR-20 | AC-06 |
| Auth gate | FR-02 | NFR-16 | AC-02 |
| Manual edit UX | FR-11 | — | AC-11 |
| Admin export guard | FR-13 | NFR-11 | AC-13 |

---

## 11. Future Consideration

- Unified notification center for absence warnings ([FR-16](../brds/03-functional-requirements.md)).
- Biometric re-auth for high-risk manual overrides.
- Configurable institution terminology (e.g., “buổi học” vs “ca học”).
