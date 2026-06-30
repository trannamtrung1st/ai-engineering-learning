# We Check — UI States

Catalog of UI states for **We Check** MVP pages and components. Every data-driven screen implements the states below per [09-page-list.md](./09-page-list.md) §9. State visuals use tokens from [04-design-tokens.md](./04-design-tokens.md) and shared components from [05-common-ui-components.md](./05-common-ui-components.md).

**Related documents:** [User flows](./10-user-flows.md) · [Wireframes](./11-wireframes.md) · [Accessibility basics](./13-accessibility-basics.md) · [Error handling](../technical/09-error-handling.md) · [Acceptance criteria](../brds/08-acceptance-mvp-future.md)

---

## 1. State Taxonomy

| State category | Purpose | Typical components |
| --- | --- | --- |
| **Loading** | Data fetch in progress | `Skeleton`, `Spinner`, `aria-busy` |
| **Empty** | Valid response with zero records | `EmptyState` with CTA — illustrated icon, warm copy, not bare gray box |
| **Error** | Recoverable or fatal fetch/action failure | `Alert` danger with recovery action; outcome-style panel on check-in |
| **Success** | Confirmed positive outcome | `Alert` success, outcome panels |
| **Idle / Ready** | Default interactive state | Form defaults, enabled controls |
| **Submitting** | Mutation in flight | Disabled inputs, button loading |
| **Permission denied** | Authorization failure | `ForbiddenPage` or inline `Alert` |
| **Stale / Polling** | Background refresh without full reload | Subtle timestamp, live regions |

---

## 2. Global State Rules

| Rule | Specification |
| --- | --- |
| No layout shift | Skeleton dimensions match final content ([NFR-19](../brds/07-non-functional-risk.md)) |
| Error copy | Vietnamese; include `errorCode` in `data-testid` for tests, not shown to users |
| Retry | Network errors offer **Thử lại**; max **3** automatic retries on check-in submit |
| Session expiry | **401** → redirect `/login?returnUrl=…` with toast *Phiên đăng nhập đã hết hạn* ([AC-02c](../brds/08-acceptance-mvp-future.md)) |
| Concurrent tabs | QR display polls independently from roster tab — no full-page reload |
| Focus management | On state transition to error/success dialog, move focus to heading ([13-accessibility-basics.md](./13-accessibility-basics.md)) |

---

## 3. State — Authentication (`/login`)

**Traces:** [FR-02](../brds/03-functional-requirements.md) · [AC-02](../brds/08-acceptance-mvp-future.md)

| State | UI | Entry condition | Exit |
| --- | --- | --- | --- |
| Idle | Empty form, enabled submit | Page load | User submits |
| Submitting | Button `loading`, fields disabled | POST `/auth/login` | Success or error |
| Error — invalid credentials | Form-level `Alert` *Email hoặc mật khẩu không đúng* | **401** | User corrects and retries |
| Error — deactivated | *Tài khoản đã bị vô hiệu hóa* | `active=false` ([AC-01c](../brds/08-acceptance-mvp-future.md)) | Contact admin |
| Success | Brief spinner then redirect | **200** | Navigate to `returnUrl` or role home |
| Already authenticated | Immediate redirect | Valid session on `/login` | Role home |

---

## 4. State — Student Check-In (`/check-in`)

**Traces:** [FR-07](../brds/03-functional-requirements.md), [FR-08](../brds/03-functional-requirements.md) · [AC-07](../brds/08-acceptance-mvp-future.md), [AC-08](../brds/08-acceptance-mvp-future.md)

### 4.1 CheckInFlow orchestrator

| State | Step | UI |
| --- | --- | --- |
| `consent` | Pre-scan | `LocationConsentBanner` visible first visit |
| `validating_token` | After scan / deep link | Inline spinner on scan step; `GET .../preflight` in flight; GPS step not mounted |
| `scanning` | 1 | `QrScannerView` active camera |
| `gps_capture` | 2 | `GpsCaptureStep` — spinner only during `requesting`/`acquiring`/`submitting` |
| `submitting` | 2→3 | Submit row spinner; `aria-busy="true"` on submit region only |
| `outcome` | 3 | `CheckInOutcomePanel` success or error variant |
| `camera_denied` | 1 | `PermissionGuideModal` `type="camera"` |

### 4.2 GpsCaptureStep substates

| Substate | Spinner | Display | `aria-busy` | Submit button |
| --- | --- | --- | --- | --- |
| `requesting` | Yes | *Đang yêu cầu quyền định vị…* | `true` | Disabled |
| `acquiring` | Yes | *Đang xác minh vị trí…* + optional accuracy hint | `true` | Disabled |
| **`ready`** | **No** | **Check icon** + *Vị trí đã sẵn sàng* (static) | **`false`** | **Enabled** |
| `submitting` | Yes | *Đang gửi điểm danh…* | `true` | Disabled |
| `denied` | No | Error copy + permission guide CTA | `false` | Disabled |

Session preflight (`sessionGate === "checking"`) may run in parallel with GPS capture but must not force GPS UI back to spinner once `ready`. **Cần bật GPS** badge on submit row clears when `gpsState === "ready"` and `capturedCoords` present.

| Substate (legacy reference) | Timeout |
| --- | --- |
| Retry | *Thử lại ({n}/3)* — up to **3** attempts |
| Permission denied | GPS guide modal — user must fix settings |

### 4.3 CheckInOutcomePanel variants (Notion pastel tints)

Each variant uses the **outcome moment** pattern: semantic wash, distinct Lucide icon (`--size-icon-lg`), `--font-display` headline, single primary CTA. See [04-design-tokens.md](./04-design-tokens.md) §13.

| Outcome | Wash | Icon (Lucide) | Primary CTA |
| --- | --- | --- | --- |
| `Present` | `--color-success-50` | `CheckCircle2` | **Xong** |
| `ExpiredQr` | `--color-warning-50` | `Clock` | **Quét lại** |
| `OutOfRadius` | `--color-warning-50` | `MapPinOff` | **Thử lại** |
| `GpsDisabled` | `--color-danger-50` | `LocateOff` | **Hướng dẫn cấp quyền** |
| `DuplicateCheckIn` | `--color-info-50` | `History` | **Xem lịch sử** |
| `SpoofSuspected` | `--color-danger-50` | `ShieldAlert` | **Liên hệ giảng viên** |
| `SessionNotActive` | `--color-warning-50` | `CalendarX` | **Đóng** |
| `NotEnrolled` | `--color-danger-50` | `UserX` | **Đóng** |
| Network error | `--color-danger-50` | `WifiOff` | **Thử lại** |

Reveal animation: scale + opacity per [03-design-system-basics.md](./03-design-system-basics.md) §9.

---

## 5. State — Student History (`/history`)

**Traces:** [FR-14](../brds/03-functional-requirements.md) · [AC-14](../brds/08-acceptance-mvp-future.md)

| State | UI |
| --- | --- |
| Loading | **3** skeleton cards |
| Empty | `EmptyState`: *Chưa có buổi học nào* — Lucide `CalendarDays` icon, `--color-text-secondary` copy, warm stone background; no CTA |
| Populated | Card list with `StatusBadge` per row |
| Loading more | Inline spinner on **Tải thêm** button |
| End of list | Hide **Tải thêm**; show *Đã hiển thị tất cả* |
| Error | `Alert` + **Thử lại** |

---

## 6. State — Instructor Session List (`/sessions`)

**Traces:** [FR-04](../brds/03-functional-requirements.md), [FR-05](../brds/03-functional-requirements.md) · [AC-04](../brds/08-acceptance-mvp-future.md)

| State | UI |
| --- | --- |
| Loading | **4** `SessionCard` skeletons |
| Empty | *Chưa có buổi học* + **Tạo buổi học** CTA |
| Populated | Grouped sections: Đang diễn ra / Nháp / Đã kết thúc |
| Error | Full-width `Alert` with retry |
| Refreshing | Subtle opacity on cards during background refetch |

**SessionCard** embeds `StatusBadge` for `Draft`, `Active`, `Closed`, `Cancelled`.

---

## 7. State — Session Detail (`/sessions/:sessionId`)

**Traces:** [FR-05](../brds/03-functional-requirements.md), [FR-06](../brds/03-functional-requirements.md) · [AC-05](../brds/08-acceptance-mvp-future.md), [AC-06](../brds/08-acceptance-mvp-future.md)

### 7.1 Page-level

| State | UI |
| --- | --- |
| Loading | Header skeleton + tab bar skeleton |
| Not found | Redirect to 404 if invalid `sessionId` |
| Forbidden | `ForbiddenPage` if not assigned instructor |
| Ready | Header with `SessionLifecycleActions` |

### 7.2 Tab — QR

| State | UI | Poll interval |
| --- | --- | --- |
| Loading token | QR skeleton + countdown placeholder | Initial fetch |
| Active QR | `QrCodeImage` + `QrCountdown` | Refresh image every **30 s** ([AC-06a](../brds/08-acceptance-mvp-future.md)) |
| Session not active | *Buổi học chưa mở* illustration ([AC-06c](../brds/08-acceptance-mvp-future.md)) | No poll |
| Token fetch error | `Alert` + **Tải lại mã QR** | Manual retry |
| Presenting | Navigates to fullscreen route | — |

### 7.3 Tab — Theo dõi (monitor)

| State | UI | Poll |
| --- | --- | --- |
| Loading | Stat card skeletons + table skeleton | Initial |
| Live | Counts + roster table | **5 s** when [FR-15](../brds/03-functional-requirements.md) enabled ([AC-15a](../brds/08-acceptance-mvp-future.md)) |
| Session closed | Banner *Buổi học đã kết thúc*; static data | Poll stops |
| Spoof alert | `SpoofAlertBadge` on affected rows | From security events |

### 7.4 Tab — Danh sách (roster edit)

| State | UI |
| --- | --- |
| Loading | Table skeleton |
| Editable | Row actions enabled per [BR-10](../brds/04-business-rules.md) |
| Edit locked | Actions disabled; tooltip *Chỉ phòng đào tạo có thể chỉnh sửa sau 24 giờ* ([AC-11b](../brds/08-acceptance-mvp-future.md)) |
| Edit dialog open | `AttendanceEditDialog` modal |
| Saving edit | Dialog submit loading |
| Edit success | Toast *Đã cập nhật*; row badge updates |

### 7.5 Lifecycle action states

| Action | Confirm dialog | Submitting | Success |
| --- | --- | --- | --- |
| Mở buổi học | *Xác nhận mở buổi học?* | Button loading | Tab switches to Theo dõi |
| Đóng buổi học | *Kết thúc điểm danh?* | Button loading | Status → `Closed` |
| Hủy (Draft) | *Hủy buổi học này?* | Button loading | Redirect to list |

**Blocked open:** GPS missing shows inline `Alert` on Cài đặt tab ([AC-04b](../brds/08-acceptance-mvp-future.md)).

---

## 8. State — Session Form (`/sessions/new`, settings tab)

**Traces:** [FR-04](../brds/03-functional-requirements.md) · [BR-07](../brds/04-business-rules.md)

| State | UI |
| --- | --- |
| Pristine | Empty or prefilled defaults |
| Dirty | Unsaved indicator on navigation away → `ConfirmDialog` |
| Validating | Field-level async checks |
| Submitting — save draft | **Lưu nháp** loading |
| Submitting — open | **Mở buổi học** loading |
| Validation error | Field errors per [08-forms-validation-ux.md](./08-forms-validation-ux.md) |
| Read-only | When session not `Draft` on settings tab |

---

## 9. State — Reports (Instructor and Admin)

**Traces:** [FR-12](../brds/03-functional-requirements.md) · [AC-12](../brds/08-acceptance-mvp-future.md)

| State | UI |
| --- | --- |
| Initial | Filters with defaults; empty table prompt *Chọn bộ lọc và nhấn Áp dụng* |
| Loading | Summary skeleton + table skeleton |
| Populated | `ReportSummaryCards` + data table |
| Empty results | *Không có dữ liệu trong khoảng thời gian đã chọn* |
| Error | `Alert` + retry |
| Permission denied | Full `ForbiddenPage` ([AC-12b](../brds/08-acceptance-mvp-future.md)) |

---

## 10. State — Admin User Management

**Traces:** [FR-01](../brds/03-functional-requirements.md) · [AC-01](../brds/08-acceptance-mvp-future.md)

### 10.1 User list

| State | UI |
| --- | --- |
| Loading | Table skeleton rows |
| Empty | *Chưa có người dùng* + **Thêm người dùng** |
| Populated | `UserListTable` with pagination |
| Filtered empty | *Không tìm thấy kết quả* + **Xóa bộ lọc** |

### 10.2 User form

| State | UI |
| --- | --- |
| Create mode | Empty `UserForm` |
| Edit mode | Prefilled; `active` switch |
| Duplicate ID | Field error on student ID ([AC-01b](../brds/08-acceptance-mvp-future.md)) |
| Deactivate confirm | `ConfirmDialog` before `active=false` |

---

## 11. State — Roster Import (`/admin/rosters/import`)

**Traces:** [FR-03](../brds/03-functional-requirements.md) · [AC-03](../brds/08-acceptance-mvp-future.md)

| State | UI |
| --- | --- |
| Idle | Drop zone ready |
| File selected | Filename + size shown |
| Parsing | Spinner *Đang đọc tệp…* |
| Preview ready | `DataTable` with ✓/✗ per row |
| Preview error | *Tệp không đúng định dạng* — required columns listed |
| Importing | Progress bar indeterminate |
| Import complete | Summary: *Đã nhập {n} dòng; {m} dòng lỗi* ([AC-03a](../brds/08-acceptance-mvp-future.md)) |
| Partial failure | Expandable error list per rejected row ([AC-03b](../brds/08-acceptance-mvp-future.md)) |

---

## 12. State — CSV Export (`/admin/export`)

**Traces:** [FR-13](../brds/03-functional-requirements.md) · [BR-09](../brds/04-business-rules.md) · [AC-13](../brds/08-acceptance-mvp-future.md)

| State | UI |
| --- | --- |
| Configure | Filters + row estimate |
| Estimating | Spinner on count |
| Ready | **Xuất CSV** enabled |
| Exporting | Button loading; prevent navigation |
| Success | Toast *Đã tải xuống*; browser download |
| Denied (wrong role) | `ForbiddenPage` or inline denial ([AC-13b](../brds/08-acceptance-mvp-future.md)) |
| Error | *Xuất thất bại* + retry |

---

## 13. State — QR Fullscreen (`/sessions/:id/qr-present`)

**Traces:** [FR-06](../brds/03-functional-requirements.md) · [NFR-20](../brds/07-non-functional-risk.md)

| State | UI |
| --- | --- |
| Entering | Fade in from black |
| Live | Large QR + countdown; minimal chrome |
| Token refresh | Cross-fade QR image; countdown resets |
| Session ended overlay | Semi-transparent overlay *Buổi học đã kết thúc* |
| Exit | **Esc** or **Thoát** returns to session detail QR tab |

---

## 14. State Matrix by Page

| Page | Loading | Empty | Error | Success | Permission |
| --- | --- | --- | --- | --- | --- |
| `/login` | — | — | ✓ | redirect | — |
| `/check-in` | ✓ | — | ✓ | ✓ outcome | — |
| `/history` | ✓ | ✓ | ✓ | — | — |
| `/sessions` | ✓ | ✓ | ✓ | — | — |
| `/sessions/:id` | ✓ | — | ✓ | lifecycle | ✓ |
| `/reports` | ✓ | ✓ | ✓ | — | ✓ |
| `/admin/users` | ✓ | ✓ | ✓ | form toast | — |
| `/admin/rosters` | ✓ | ✓ | ✓ | — | — |
| `/admin/rosters/import` | ✓ | — | ✓ | ✓ summary | — |
| `/admin/reports` | ✓ | ✓ | ✓ | — | — |
| `/admin/export` | ✓ | — | ✓ | ✓ download | ✓ |
| `/forbidden` | — | — | — | — | ✓ |
| `*` 404 | — | — | — | — | — |

---

## 15. Polling and Real-Time State

| Component | Mechanism | Interval | Stop condition |
| --- | --- | --- | --- |
| `QrCountdown` | Client timer + server token fetch | **30 s** | Session not `Active` |
| `SessionMonitorDashboard` | HTTP poll | **5 s** | Session `Closed` or tab hidden |
| `AttendanceRosterTable` (monitor) | Same poll as dashboard | **5 s** | Tab inactive > **30 s** pauses poll |

Tab visibility: use `document.visibilityState` to pause polls when backgrounded ([NFR-08](../brds/07-non-functional-risk.md)).

---

## 16. Future Consideration

- WebSocket push for monitor tab replacing poll ([FR-15](../brds/03-functional-requirements.md)).
- Optimistic roster edit with rollback on failure.
- Offline queue state for check-in (explicitly out of MVP scope).
- Skeleton variants for slow 3G throttling per [NFR-04](../brds/07-non-functional-risk.md).
