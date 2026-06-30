# We Check — Wireframes

Low-fidelity wireframe specifications for **We Check** MVP screens. Layouts reference components from [05-common-ui-components.md](./05-common-ui-components.md), [07-event-specific-components.md](./07-event-specific-components.md), and shells from [06-app-layout-components.md](./06-app-layout-components.md). Routes defined in [09-page-list.md](./09-page-list.md).

**Related documents:** [User flows](./10-user-flows.md) · [UI states](./12-ui-states.md) · [Design overview](./01-design-overview.md) · [Design tokens](./04-design-tokens.md)

---

## 1. Wireframe Conventions

| Convention | Specification |
| --- | --- |
| Viewport — student | **375 × 812** px (iPhone baseline); min width **320** px |
| Viewport — instructor/admin | **1280 × 800** px desktop; collapses to **768** px tablet |
| Grid | **4**-column mobile, **12**-column desktop |
| Touch targets | Min **44 × 44** px ([NFR-17](../brds/07-non-functional-risk.md)) |
| Annotation | `[ComponentName]` in brackets; `---` dividers for regions |
| Color in wireframes | Grayscale only; status colors applied in high-fidelity per [04-design-tokens.md](./04-design-tokens.md) |

---

## 2. Wireframe — Login (`/login`)

**Layout:** `AuthLayout` · **Traces:** [FR-02](../brds/03-functional-requirements.md) · [AC-02](../brds/08-acceptance-mvp-future.md)

```
┌─────────────────────────────────────┐
│           [Logo] We Check           │
│                                     │
│   ┌─────────────────────────────┐   │
│   │ Email / Tên đăng nhập       │   │
│   └─────────────────────────────┘   │
│   ┌─────────────────────────────┐   │
│   │ Mật khẩu              [👁]  │   │
│   └─────────────────────────────┘   │
│                                     │
│   ┌─────────────────────────────┐   │
│   │      Đăng nhập  [Button]    │   │
│   └─────────────────────────────┘   │
│                                     │
│   [Alert] — form-level error slot   │
└─────────────────────────────────────┘
```

| Region | Component | Notes |
| --- | --- | --- |
| Header | Product logo + wordmark | Centered |
| Form | `LoginForm` | Two fields; password toggle |
| CTA | `Button` primary full-width | Loading state on submit |
| Footer | — | No self-registration link in MVP |

---

## 2a. Wireframe — Setup (`/setup`)

**Layout:** `AuthLayout` (no login link) · **Traces:** [FR-17](../brds/03-functional-requirements.md) · [AC-17](../brds/08-acceptance-mvp-future.md)

```
┌─────────────────────────────────────┐
│   Thiết lập We Check lần đầu        │
│                                     │
│   [SetupAdminForm fields]           │
│   Mã cán bộ / Họ tên / Email / MK   │
│                                     │
│   [Button primary] Tạo tài khoản    │
└─────────────────────────────────────┘
```

---

## 2b. Wireframe — Admin Home (`/admin`)

**Layout:** `AdminLayout` · **Traces:** [FR-18](../brds/03-functional-requirements.md) · [AC-18c](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Trang chủ quản trị                      │
│ Trang chủ│  ┌────────┐ ┌────────┐ ┌────────┐        │
│ Người    │  │ Người  │ │ Danh   │ │ Thêm   │        │
│ dùng …   │  │ dùng   │ │ sách   │ │ lớp    │        │
│          │  └────────┘ └────────┘ └────────┘        │
│          │  [RoleHomeHub / QuickActionGrid]         │
└──────────┴──────────────────────────────────────────┘
```

Cards omitted when permission missing.

---

## 3. Wireframe — Student Check-In Scanner (`/check-in/scan`)

**Layout:** `StudentLayout` (bottom nav hidden) · **Traces:** [FR-07](../brds/03-functional-requirements.md) · [AC-07](../brds/08-acceptance-mvp-future.md)

```
┌─────────────────────────────────────┐
│ ← Quay lại          Điểm danh       │
├─────────────────────────────────────┤
│                                     │
│   ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐     │
│   │                           │     │
│   │    [Camera viewfinder]    │     │
│   │                           │     │
│   └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘     │
│                                     │
│   Đưa mã QR vào khung hình          │
│                                     │
├─────────────────────────────────────┤
│ [LocationConsentBanner] — first use │
└─────────────────────────────────────┘
```

| Region | Component | Behavior |
| --- | --- | --- |
| App bar | Back + title | Back returns to `/check-in` hub |
| Viewfinder | `QrScannerView` | Rounded rect overlay on camera stream |
| Hint | Static text | Below viewfinder |
| Consent | `LocationConsentBanner` | Dismissible; links to privacy note |

---

## 4. Wireframe — GPS Capture and Outcome (check-in steps)

**Traces:** [FR-08](../brds/03-functional-requirements.md) · [AC-08](../brds/08-acceptance-mvp-future.md)

### 4.1 GPS acquiring

```
┌─────────────────────────────────────┐
│         Xác minh vị trí             │
├─────────────────────────────────────┤
│                                     │
│         [Spinner — large]           │
│                                     │
│   Đang xác minh vị trí của bạn…     │
│   Vui lòng đứng trong phòng học     │
│                                     │
│   [Progress: attempt 1/3]           │
│                                     │
│   [Button outline] Hủy              │
└─────────────────────────────────────┘
```

### 4.1b GPS ready (no spinner)

```
┌─────────────────────────────────────┐
│  SWE-101 · HESD-01 · Phòng A101     │
│         Xác minh vị trí             │
├─────────────────────────────────────┤
│                                     │
│         [Icon — check]              │
│                                     │
│      Vị trí đã sẵn sàng             │
│   (static — no Spinner)             │
│                                     │
│   [Button primary] Xác nhận điểm    │
│                    danh             │
└─────────────────────────────────────┘
```

`aria-busy="false"`; submit enabled immediately ([AC-08f](../brds/08-acceptance-mvp-future.md)).

### 4.2 Success outcome

```
┌─────────────────────────────────────┐
│         [Icon — check circle]       │
│                                     │
│      Điểm danh thành công           │
│                                     │
│   SWE-101 — Buổi 12                 │
│   08:42, 15/03/2026                 │
│                                     │
│   [StatusBadge] Có mặt              │
│                                     │
│   [Button primary] Xong             │
│   [Button ghost] Quét mã khác       │
└─────────────────────────────────────┘
```

### 4.3 Error outcome (template)

```
┌─────────────────────────────────────┐
│         [Icon — warning]            │
│                                     │
│      {Outcome title — vi-VN}        │
│      {Explanation paragraph}        │
│                                     │
│   [Alert info] Hướng dẫn tiếp theo   │
│                                     │
│   [Button primary] {Primary action} │
│   [Button ghost] Liên hệ giảng viên │
└─────────────────────────────────────┘
```

Component: `CheckInOutcomePanel` — Notion pastel outcome moment; variant driven by `CheckInOutcome` enum with distinct icon, card-tint wash, and semibold headline per [04-design-tokens.md](./04-design-tokens.md) §13.

---

## 5. Wireframe — Student History (`/history`)

**Layout:** `StudentLayout` with bottom nav · **Traces:** [FR-14](../brds/03-functional-requirements.md) · [AC-14](../brds/08-acceptance-mvp-future.md)

```
┌─────────────────────────────────────┐
│         Lịch sử chuyên cần          │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ SWE-101 · 15/03/2026            │ │
│ │ [StatusBadge] Có mặt · 08:42    │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ SWE-101 · 12/03/2026            │ │
│ │ [StatusBadge] Vắng              │ │
│ └─────────────────────────────────┘ │
│           ...                       │
│   [Button outline] Tải thêm         │
├─────────────────────────────────────┤
│  [Nav] Điểm danh  |  Lịch sử ●     │
└─────────────────────────────────────┘
```

---

## 6. Wireframe — Instructor Session List (`/sessions`)

**Layout:** `InstructorLayout` · **Traces:** [FR-04](../brds/03-functional-requirements.md) · [AC-04](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ [PageHeader] Buổi học    [+ Tạo buổi học] │
│          ├──────────────────────────────────────────┤
│ Buổi học●│ Đang diễn ra                           │
│ Báo cáo  │ ┌──────────────────────────────────────┐ │
│          │ │ [SessionCard] HESD-01 / SWE-101        │ │
│          │ │ Phòng A101 · [StatusBadge] Đang mở   │ │
│          │ └──────────────────────────────────────┘ │
│          │ Nháp                                     │
│          │ ┌──────────────────────────────────────┐ │
│          │ │ [SessionCard] ... [StatusBadge] Nháp │ │
│          │ └──────────────────────────────────────┘ │
│          │ Đã kết thúc                              │
│          │ ┌──────────────────────────────────────┐ │
│          │ │ [SessionCard] ...                    │ │
│          │ └──────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────┘
```

Groups: `Active` first, then `Draft`, then `Closed` — see [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md).

---

## 7. Wireframe — Create Session (`/sessions/new`)

**Layout:** `InstructorLayout` · **Traces:** [FR-04](../brds/03-functional-requirements.md) · [BR-07](../brds/04-business-rules.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ [PageHeader] Tạo buổi học mới             │
│          ├──────────────────────────────────────────┤
│          │ [SplitView]                                │
│          │ ┌─────────────────┬──────────────────────┐│
│          │ │ [SessionForm]   │ [GpsMapPicker]       ││
│          │ │ Lớp [Select]    │     (map pin)        ││
│          │ │ Môn [Select]    │                      ││
│          │ │ Ngày [Date]     │ Lat/Lng readout      ││
│          │ │ Giờ [Time]      │ Bán kính [100] m     ││
│          │ │ Phòng [Input]   │                      ││
│          │ └─────────────────┴──────────────────────┘│
│          │ [FormActions] Lưu nháp | Mở buổi học      │
└──────────┴──────────────────────────────────────────┘
```

Map panel required before **Mở buổi học** is enabled.

---

## 8. Wireframe — Session Detail (`/sessions/:sessionId`)

**Layout:** `InstructorLayout` + tabs · **Traces:** [FR-05](../brds/03-functional-requirements.md), [FR-06](../brds/03-functional-requirements.md) · [AC-05](../brds/08-acceptance-mvp-future.md), [AC-06](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ HESD-01 / SWE-101  [StatusBadge] Đang mở │
│          │ [SessionLifecycleActions] Đóng buổi học    │
│          ├──────────────────────────────────────────┤
│          │ [Tabs] QR | Theo dõi ● | Danh sách | Cài đặt│
│          ├──────────────────────────────────────────┤
│          │ ┌────────────────────────────────────┐   │
│          │ │     [QrCodeImage — large]          │   │
│          │ │     Còn 24 giây [QrCountdown]      │   │
│          │ │ [Button] Trình chiếu QR            │   │
│          │ └────────────────────────────────────┘   │
└──────────┴──────────────────────────────────────────┘
```

**Tab default:** `Theo dõi` when `Active`; `Cài đặt` when `Draft` ([09-page-list.md](./09-page-list.md) §4.3).

### 8.1 Tab — Theo dõi (monitor)

```
┌──────────────────────────────────────────┐
│ [StatCard] 98/120  [StatCard] 22 Vắng    │
├──────────────────────────────────────────┤
│ [TableToolbar] Tìm kiếm | Lọc trạng thái │
├──────────────────────────────────────────┤
│ [AttendanceRosterTable]                  │
│ STT | Họ tên | MSSV | Trạng thái | ...   │
│  1  | Nguyễn A | SV001 | [Badge] Có mặt │
│  2  | Trần B   | SV002 | [Badge] Chờ    │
└──────────────────────────────────────────┘
```

### 8.2 Tab — Danh sách (roster with edit)

Same table as monitor with **Chỉnh sửa** row action opening `AttendanceEditDialog`.

---

## 9. Wireframe — QR Fullscreen Presentation (`/sessions/:id/qr-present`)

**Layout:** `FullscreenLayout` · **Traces:** [FR-06](../brds/03-functional-requirements.md) · [NFR-20](../brds/07-non-functional-risk.md)

```
┌─────────────────────────────────────────────────────┐
│ ■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■ │
│ ■■■                                               ■ │
│ ■■■     ┌─────────────────────────────┐           ■ │
│ ■■■     │                             │           ■ │
│ ■■■     │      [QR — 60% viewport]    │           ■ │
│ ■■■     │                             │           ■ │
│ ■■■     └─────────────────────────────┘           ■ │
│ ■■■                                               ■ │
│ ■■■     HESD-01 — SWE-101                         ■ │
│ ■■■     Quét mã để điểm danh                      ■ │
│ ■■■     ●●●●●●●●○○  24 giây                       ■ │
│ ■■■                                    [Esc] Thoát ■ │
│ ■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■ │
└─────────────────────────────────────────────────────┘
```

Black background (`#000`); QR minimum **280 × 280** px on projector; countdown high contrast.

---

## 10. Wireframe — Instructor Reports (`/reports`)

**Traces:** [FR-12](../brds/03-functional-requirements.md) · [AC-12](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ [PageHeader] Báo cáo chuyên cần         │
│          ├──────────────────────────────────────────┤
│          │ [ReportFilterBar]                        │
│          │ Lớp | Môn | Từ ngày | Đến ngày | Áp dụng│
│          ├──────────────────────────────────────────┤
│          │ [ReportSummaryCards]                     │
│          │ Tổng buổi | TB có mặt | Tổng vắng       │
│          ├──────────────────────────────────────────┤
│          │ [SessionReportTable]                     │
│          │ Ngày | Lớp | Môn | Có mặt | Vắng | →    │
└──────────┴──────────────────────────────────────────┘
```

---

## 11. Wireframe — Admin User List (`/admin/users`)

**Traces:** [FR-01](../brds/03-functional-requirements.md) · [AC-01](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ [PageHeader] Người dùng  [+ Thêm]        │
│          ├──────────────────────────────────────────┤
│          │ [TableToolbar] 🔍 Tìm theo tên/MSSV/email │
│          │              [Select] Vai trò | Trạng thái │
│          ├──────────────────────────────────────────┤
│          │ [UserListTable]                          │
│          │ Họ tên | MSSV | Email | Vai trò | TT | → │
│          ├──────────────────────────────────────────┤
│          │ [Pagination] Trang 1 / 12                │
└──────────┴──────────────────────────────────────────┘
```

---

## 12. Wireframe — Roster Import (`/admin/rosters/import`)

**Traces:** [FR-03](../brds/03-functional-requirements.md) · [AC-03](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ [PageHeader] Nhập danh sách lớp          │
│          ├──────────────────────────────────────────┤
│          │ [RosterImportPanel]                      │
│          │ ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   │
│          │   Kéo thả CSV hoặc [Chọn tệp]          │
│          │ └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘   │
│          │ Cột bắt buộc: MSSV, Họ tên, Mã lớp, Mã môn│
│          ├──────────────────────────────────────────┤
│          │ [DataTable preview] ✓ / ✗ per row        │
│          ├──────────────────────────────────────────┤
│          │ [FormActions] Hủy | Xác nhận nhập (128)  │
└──────────┴──────────────────────────────────────────┘
```

---

## 13. Wireframe — Admin CSV Export (`/admin/export`)

**Traces:** [FR-13](../brds/03-functional-requirements.md) · [AC-13](../brds/08-acceptance-mvp-future.md)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │ [PageHeader] Xuất dữ liệu CSV            │
│          ├──────────────────────────────────────────┤
│          │ [ReportFilterBar] — same as reports      │
│          ├──────────────────────────────────────────┤
│          │ [CsvExportPanel]                         │
│          │ Ước tính: ~1.240 dòng                    │
│          │ [Alert info] Dữ liệu tuân thủ NĐ 13/2023   │
│          │ [Button primary] Xuất CSV                │
└──────────┴──────────────────────────────────────────┘
```

---

## 14. Wireframe — Forbidden and Not Found

### 14.1 Forbidden (`/forbidden`)

```
┌─────────────────────────────────────┐
│         [Icon — lock]               │
│   Bạn không có quyền truy cập       │
│   {Optional resource context}       │
│   [Button] Về trang chủ             │
└─────────────────────────────────────┘
```

### 14.2 Not Found (`*`)

```
┌─────────────────────────────────────┐
│         404                         │
│   Không tìm thấy trang              │
│   [Button] Về trang chủ             │
└─────────────────────────────────────┘
```

### 14.3 Shell overview (`/`) — route discovery

Unauthenticated only ([AC-18f](../brds/08-acceptance-mvp-future.md), [AC-18g](../brds/08-acceptance-mvp-future.md)).

```
┌─────────────────────────────────────┐
│ Hệ thống giao diện We Check         │
│ {component showcase — badges, QR}   │
│ Các trạng thái điểm danh            │
│ {outcome panels}                    │
├─────────────────────────────────────┤
│ Đi tới trang                        │
│ ┌─────────────┐ ┌─────────────┐     │
│ │ Đăng nhập   │ │ Điểm danh   │     │
│ │ /login      │ │ /check-in   │     │
│ └─────────────┘ └─────────────┘     │
│ ┌─────────────┐ ┌─────────────┐     │
│ │ Buổi học    │ │ Quản trị    │     │
│ │ /sessions   │ │ /admin      │     │
│ └─────────────┘ └─────────────┘     │
└─────────────────────────────────────┘
```

---

## 15. Responsive Behavior Summary

| Screen group | Breakpoint | Layout change |
| --- | --- | --- |
| Student check-in | < **768** px | Single column; full-bleed scanner |
| Student history | < **768** px | Card list; bottom nav fixed |
| Instructor forms | < **1024** px | `SplitView` stacks: form above map |
| Admin tables | < **768** px | Horizontal scroll on table; filters collapse to drawer |
| QR fullscreen | Any | Always fullscreen; min QR **60%** short edge |

---

## 16. Future Consideration

- High-fidelity Figma frames linked from this doc.
- `/admin/policy` wireframe for absence threshold configuration ([FR-16](../brds/03-functional-requirements.md)).
- Print-friendly report layout at `/reports/print`.
- Dark-mode variants for instructor projection (QR tab already uses dark fullscreen).
