# Attendly — Wireframes

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [09-page-list.md](./09-page-list.md) · [10-user-flows.md](./10-user-flows.md) · [12-ui-states.md](./12-ui-states.md) · [06-app-layout-components.md](./06-app-layout-components.md) · [07-domain-specific-components.md](./07-domain-specific-components.md)

## 1. Purpose and scope

This document provides **low-fidelity wireframe layouts** for Attendly MVP pages (PG-xx). Wireframes describe information hierarchy, primary actions, and component placement — not final pixel values. Visual styling follows [DESIGN.md](./DESIGN.md) Neobrutalism tokens; component IDs reference [07-domain-specific-components.md](./07-domain-specific-components.md).

### 1.1 Wireframe conventions

| Symbol | Meaning |
| --- | --- |
| `[Button]` | Primary or secondary action control |
| `[Badge]` | `StatusBadge` chip |
| `[...]` | Truncated repeating content |
| `|---|` | Table row or list divider |
| `*` | Primary action for the page (`FR-UI-01`) |

Layout families: `LAY-01` (student mobile), `LAY-02` (lecturer), `LAY-03` (admin), `LAY-04` (audit) per [06-app-layout-components.md](./06-app-layout-components.md).

---

## 2. Auth and entry wireframes

### 2.1 PG-01 — Login (`LAY-01` / centered card)

```
┌─────────────────────────────────────┐
│           Attendly logo             │
│     Đăng nhập tài khoản             │
├─────────────────────────────────────┤
│  Email / Mã sinh viên               │
│  ┌─────────────────────────────┐    │
│  │                             │    │
│  └─────────────────────────────┘    │
│  Mật khẩu                           │
│  ┌─────────────────────────────┐    │
│  │  ••••••••                   │    │
│  └─────────────────────────────┘    │
│  [FeedbackAlert — error if any]     │
│                                     │
│  [ * Đăng nhập ]                    │
└─────────────────────────────────────┘
```

Trace: FRM-01, `FR-15`, `FR-36`.

### 2.2 PG-02 — Check-in entry (`LAY-01`)

**State: submitting / awaiting result**

```
┌─────────────────────────────────────┐
│  Attendly                           │
├─────────────────────────────────────┤
│                                     │
│     ◌  Đang xử lý điểm danh...      │
│                                     │
│  (spinner — minimal chrome)         │
│                                     │
└─────────────────────────────────────┘
```

On completion, full viewport yields to `CheckInResultScreen` (DC-04). See §3.1.

---

## 3. Student wireframes

### 3.1 PG-02 result — `CheckInResultScreen` (DC-04)

**Success — Present**

```
┌─────────────────────────────────────┐
│                                     │
│            ✓ (large icon)           │
│                                     │
│   Điểm danh thành công              │
│   Có mặt                            │
│                                     │
│   14:32 · 02/07/2026                │
│                                     │
│   [ Xem lịch sử điểm danh ]         │
│                                     │
└─────────────────────────────────────┘
```

**Failure — ExpiredQr**

```
┌─────────────────────────────────────┐
│  [!] Mã QR đã hết hạn               │
│  Vui lòng quét mã mới trên màn      │
│  chiếu.                             │
│                                     │
│  [ * Quét lại ]                     │
└─────────────────────────────────────┘
```

Trace: `AC-UI-02`, `AC-UI-03`, `FR-UI-03`.

### 3.2 PG-02 — `GpsPermissionPrompt` (DC-05)

```
┌─────────────────────────────────────┐
│  📍 Xác minh vị trí                 │
├─────────────────────────────────────┤
│  Attendly cần vị trí một lần để     │
│  xác nhận bạn đang ở lớp học.       │
│  Chúng tôi không theo dõi liên tục. │
│                                     │
│  [ * Cho phép vị trí ]              │
│  [ Bỏ qua — xem hướng dẫn ]         │
└─────────────────────────────────────┘
```

### 3.3 PG-03 — My attendance history (`LAY-01`)

```
┌─────────────────────────────────────┐
│  Lịch sử điểm danh                  │
├─────────────────────────────────────┤
│  [Học kỳ ▼]  [Lớp HP ▼]  [TT ▼]    │
├─────────────────────────────────────┤
│  CS101-A · Buổi 12                  │
│  [Present]  14:30 · QR              │
│  |---|                               │
│  CS101-A · Buổi 11                  │
│  [Late]     09:45 · QR              │
│  |---|                               │
│  [...]                              │
├─────────────────────────────────────┤
│  ‹ 1 2 3 ›                          │
└─────────────────────────────────────┘
```

Component: `AttendanceHistoryList` (DC-10). Trace: `FR-37`, PG-03 matrix in [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) §0.

---

## 4. Lecturer wireframes

### 4.1 PG-04 — Session list (`LAY-02` + `LAY-03` shell)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Buổi học hôm nay                        │
│ Nav      │  [Search...........] [Ngày▼] [TT▼] [Sort]│
│          ├──────────────────────────────────────────┤
│ Sessions*│  Section   Time    Room   [Badge]  Act  │
│ Reports  │  |---|                                     │
│          │  CS101-A  08:00  A201  [Open]   [Mở →]   │
│          │  |---|                                     │
│          │  CS202-B  10:00  B102  [Sched]  [Mở →]   │
│          │  |---|                                     │
│          │  [...]                                    │
│          ├──────────────────────────────────────────┤
│          │  ‹ Trang 1 / 5 ›                        │
└──────────┴──────────────────────────────────────────┘
```

Components: `TableToolbar`, `DataTable`, `SessionControlBar` context. Trace: `FR-10`, `AC-01`.

### 4.2 PG-05 — Session control / QR display (`LAY-02`)

**State: Open**

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  CS101-A · Buổi 15    [Open]             │
│          │  A201 · 08:00–10:00                      │
│          │  [ * Đóng điểm danh ]    [Xem danh sách]  │
│          ├──────────────────────────────────────────┤
│          │  ┌────────────────────────────────────┐  │
│          │  │     QrDisplayPanel (DC-01)         │  │
│          │  │                                    │  │
│          │  │         ████████████               │  │
│          │  │         ██ QR ██                   │  │
│          │  │         ████████████               │  │
│          │  │                                    │  │
│          │  │     QrCountdownRing  0:24          │  │
│          │  └────────────────────────────────────┘  │
│          │  Present: 28  Late: 2  Chờ: 15         │
└──────────┴──────────────────────────────────────────┘
```

**State: Scheduled** — QR panel hidden; primary action is `[ * Mở điểm danh ]`.  
**State: Closed** — QR locked message; no open/close CTAs. Trace: `AC-02`, `AC-UI-06`.

### 4.3 PG-06 — Live roster (`LAY-02` split)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Danh sách lớp · CS101-A Buổi 15 [Open]  │
│          │  [Search tên/MSSV...] [TT▼] [Sort]       │
│          ├──────────────────────────────────────────┤
│          │  [28 Present] [2 Late] [15 Chờ] [3 Lỗi]  │
│          ├──────────────────────────────────────────┤
│          │  MSSV    Tên          Trạng thái   Act   │
│          │  |---|                                       │
│          │  20100   Nguyễn A    [Present]    [Sửa]    │
│          │  20101   Trần B      [Late]      [Sửa]    │
│          │  20102   Lê C        [Pending]    [Sửa]    │
│          │  20103   Phạm D      [ExpiredQr]  [Sửa]   │
│          │  |---|                                       │
│          │  [...]  (virtualized scroll)                │
└──────────┴──────────────────────────────────────────┘
```

Component: `LiveRosterPanel` (DC-06), `ManualCorrectionDialog` on row action. Trace: `FR-19`, `AC-13`.

---

## 5. Admin setup wireframes

### 5.1 PG-07–PG-09 — Admin listing pattern (`LAY-03`)

All admin list pages share this wireframe skeleton; labels change per entity.

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Học kỳ                    [ * Tạo mới ]  │
│          │  [Search...........] [Bộ lọc ▼] [Sort ▼] │
│          ├──────────────────────────────────────────┤
│          │  Mã      Tên           Bắt đầu   Active  │
│          │  |---|                                       │
│          │  HK2026  Học kỳ 1/26   01/02    [✓]       │
│          │  |---|                                       │
│          │  [...]                                    │
│          ├──────────────────────────────────────────┤
│          │  ‹ 1 2 ›   25 / trang                    │
└──────────┴──────────────────────────────────────────┘
```

Applies to: PG-07 Terms, PG-08 Courses, PG-09 Class sections, PG-11 Rooms, PG-12 Policies. `TableToolbar` mandatory per [05-common-ui-components.md](./05-common-ui-components.md) §4.

### 5.2 PG-10 — Enrollment import (`LAY-03`)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Nhập danh sách · CS101-A                 │
│          ├──────────────────────────────────────────┤
│          │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐      │
│          │  │  Kéo thả file CSV vào đây      │      │
│          │  │  hoặc [ Chọn file ]             │      │
│          │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘      │
│          │  enrollments.csv (12 KB)                │
│          │  [ * Nhập dữ liệu ]                     │
│          ├──────────────────────────────────────────┤
│          │  Kết quả: 45 chấp nhận · 3 lỗi          │
│          │  Dòng  Lỗi              Chi tiết         │
│          │  |---|                                       │
│          │  12    StudentNotFound   MSSV không tồn tại │
│          │  |---|                                       │
└──────────┴──────────────────────────────────────────┘
```

Trace: FRM-06, `FR-04`.

### 5.3 PG-12 — Policy form with preview

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Cấu hình chính sách điểm danh            │
│          ├──────────────────┬───────────────────────┤
│          │  FRM-07 fields   │ PolicyResolutionSummary│
│          │  Phạm vi [○]     │ (DC-09 accordion)     │
│          │  Cửa sổ có mặt   │ ▶ GPS: 100m (section) │
│          │  Cửa sổ trễ      │ ▶ Late: 15 phút       │
│          │  GPS [toggle]    │ ▶ Precedence chain    │
│          │  [ * Lưu ]       │                       │
└──────────┴──────────────────┴───────────────────────┘
```

---

## 6. Reporting and audit wireframes

### 6.1 PG-13 — Attendance reports (`LAY-03` / `LAY-04`)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Báo cáo điểm danh                        │
│          │  [Search MSSV...] [HK▼][Lớp▼][TT▼][Từ–Đến]│
│          │  [Sort ▼]              [ * Xuất CSV ]       │
│          ├──────────────────────────────────────────┤
│          │  MSSV   Tên    Lớp    Buổi   [Status]    │
│          │  |---|                                       │
│          │  20100  Ng.A   CS101  #12    [Present]    │
│          │  |---|                                       │
│          │  [...]                                    │
│          ├──────────────────────────────────────────┤
│          │  ‹ 1 2 3 ›                                 │
└──────────┴──────────────────────────────────────────┘
```

### 6.2 PG-14 — Export scope dialog (modal on PG-13)

```
┌─────────────────────────────────────┐
│  Xác nhận xuất CSV                  │
├─────────────────────────────────────┤
│  ExportScopeSummary (DC-11)         │
│  Học kỳ: HK2026                     │
│  Lớp: CS101-A                       │
│  Trạng thái: Tất cả                 │
│  Phạm vi: 156 bản ghi (theo quyền)  │
│                                     │
│  Hành động này được ghi audit.      │
│                                     │
│  [ Hủy ]    [ * Xuất CSV ]          │
└─────────────────────────────────────┘
```

Trace: `AC-UI-08`, `FR-27`, `FR-30`.

### 6.3 PG-15 — Audit log review (`LAY-04`)

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Nhật ký kiểm toán                        │
│          │  [Search actor/target] [Loại▼][Từ–Đến]    │
│          ├──────────────────┬───────────────────────┤
│          │  AuditEntryRow   │  Chi tiết (accordion) │
│          │  list            │                       │
│          │  |---|            │  Actor: lecturer@...  │
│          │  14:32 Edit      │  Target: SV 20100     │
│          │  Attendance      │  Old: Absent          │
│          │  |---|            │  New: Manual Present │
│          │  14:30 CheckIn   │  Reason: máy hỏng     │
│          │  Success         │                       │
│          │  |---|            │                       │
│          │  [...]           │                       │
└──────────┴──────────────────┴───────────────────────┘
```

Trace: `FR-29`, `FR-32`.

---

## 7. Responsive wireframe notes

| Layout | Breakpoint behavior |
| --- | --- |
| `LAY-01` | Single column; full-width CTAs; min 44px touch targets (`NFR-UI-11`) |
| `LAY-02` | QR panel stacks above roster on tablet; split panel on desktop |
| `LAY-03` | `SidebarNav` collapses to drawer below 1024px; `TableToolbar` filters wrap to second row |
| `LAY-04` | Audit detail panel becomes bottom sheet on mobile |

---

## 8. Wireframe-to-page traceability

| Wireframe § | Page ID | Route | Primary flow |
| --- | --- | --- | --- |
| §2 | PG-01, PG-02 | `/login`, `/check-in` | FLOW-01, FLOW-14 |
| §3 | PG-02, PG-03 | `/check-in`, `/me/attendance` | FLOW-01–04 |
| §4 | PG-04–PG-06 | `/lecturer/sessions/*` | FLOW-05–08 |
| §5 | PG-07–PG-12 | `/admin/*` | FLOW-09–11 |
| §6 | PG-13–PG-15 | `/reports/*`, `/audit/*` | FLOW-12–13 |

---

## 9. Future consideration

- High-fidelity Figma frames linked from `DESIGN.md` when design tooling is adopted.
- Projector "presentation mode" wireframe with enlarged QR and hidden chrome.
- Dispute investigation workbench combining audit detail and attempt timeline.
