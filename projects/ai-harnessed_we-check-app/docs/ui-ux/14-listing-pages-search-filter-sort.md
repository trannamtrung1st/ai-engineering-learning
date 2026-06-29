# We Check — Listing Pages: Search, Filter, and Sort

Unified listing UX patterns for **We Check** tables and card lists: search, filter, sort, pagination, and empty states. Applies to pages in [09-page-list.md](./09-page-list.md) that display collections.

**Related documents:** [User flows](./10-user-flows.md) · [UI states](./12-ui-states.md) · [Common UI components](./05-common-ui-components.md) · [Accessibility basics](./13-accessibility-basics.md) · [Functional requirements](../brds/03-functional-requirements.md)

---

## 1. Listing Scope

| Page | Route | Layout pattern | Primary component |
| --- | --- | --- | --- |
| Session list | `/sessions` | Grouped cards | `SessionCard` |
| Attendance history | `/history` | Card list + load more | `AttendanceHistoryList` |
| Session roster | `/sessions/:id` (tabs) | Data table | `AttendanceRosterTable` |
| Instructor reports | `/reports` | Filter bar + table | `SessionReportTable` |
| Admin users | `/admin/users` | Toolbar + table | `UserListTable` |
| Class rosters | `/admin/rosters` | Toolbar + table | `ClassRosterTable` |
| Admin reports | `/admin/reports` | Filter bar + table | `SessionReportTable` |

**Traces:** [FR-12](../brds/03-functional-requirements.md), [FR-14](../brds/03-functional-requirements.md) · [AC-12](../brds/08-acceptance-mvp-future.md), [AC-14](../brds/08-acceptance-mvp-future.md), [AC-15](../brds/08-acceptance-mvp-future.md)

---

## 2. Listing Architecture

```
┌─────────────────────────────────────────┐
│ [PageHeader]                            │
├─────────────────────────────────────────┤
│ [TableToolbar] or [ReportFilterBar]     │
│  Search | Filters | Sort | Actions      │
├─────────────────────────────────────────┤
│ Active filter chips (removable)         │
├─────────────────────────────────────────┤
│ Results: table | cards | empty state    │
├─────────────────────────────────────────┤
│ [Pagination] or [Load more]             │
└─────────────────────────────────────────┘
```

| Layer | Component | Responsibility |
| --- | --- | --- |
| Toolbar | `TableToolbar` | Inline search + quick filters (admin lists) |
| Filter bar | `ReportFilterBar` | Multi-field date/class/subject filters (reports) |
| Chips | `FilterChip` | Show applied filters; click **×** to remove |
| Results | Domain table/card | Render rows |
| Footer | `Pagination` or button | Navigate pages |

---

## 3. Listing — Search

### 3.1 Global rules

| Rule | Value |
| --- | --- |
| Debounce | **300 ms** after last keystroke |
| Min characters | **2** before API search (admin users); **0** for client-only small lists |
| Case | Case-insensitive diacritic-aware match for Vietnamese names |
| Clear | **×** in input clears and refetches |
| URL sync | Admin user search persists in `?q=` query param for shareable state |

### 3.2 Per-page search fields

| Page | Placeholder (vi-VN) | Searches |
| --- | --- | --- |
| `/admin/users` | *Tìm theo tên, MSSV, email* | `displayName`, `studentId`, `email` |
| `/sessions/:id` roster | *Tìm sinh viên…* | `displayName`, `studentId` |
| `/admin/rosters` | *Tìm theo mã lớp* | `classCode`, `className` |
| `/admin/rosters/:classCode` | *Tìm trong lớp…* | Enrolled student name, ID |

Reports use structured filters only — no free-text search in MVP.

---

## 4. Listing — Filters

### 4.1 TableToolbar filters (admin lists)

| Page | Filter controls | Default |
| --- | --- | --- |
| `/admin/users` | `Select` Vai trò: Tất cả / Sinh viên / Giảng viên / Admin; `Select` Trạng thái: Tất cả / Hoạt động / Ngừng hoạt động | All |
| `/admin/rosters` | `Select` Khóa học (if multiple cohorts) | Current cohort |

Filters apply on change (no separate Apply button) for toolbar pattern.

### 4.2 ReportFilterBar (reports and export)

Shared by `/reports`, `/reports/sessions`, `/admin/reports`, `/admin/export`.

| Field | Control | Required | Notes |
| --- | --- | --- | --- |
| Lớp | `Select` | Yes for instructor; optional all for admin | Instructor sees assigned classes only ([BR-08](../brds/04-business-rules.md)) |
| Môn | `Select` | Depends on class | Cascading: loads subjects for selected class |
| Từ ngày | Date picker | Yes | Default: start of current month |
| Đến ngày | Date picker | Yes | Must be ≥ Từ ngày |
| Áp dụng | `Button` primary | — | Triggers fetch; disabled until valid range |

**Instructor scope:** Unassigned class not in dropdown ([AC-12b](../brds/08-acceptance-mvp-future.md)).  
**Admin scope:** All classes; report within **10 minutes** of session close ([AC-12c](../brds/08-acceptance-mvp-future.md)).

### 4.3 Session list grouping (implicit filter)

`/sessions` does not expose a filter bar. Sessions are **grouped** by status:

| Group label | `SessionStatus` values | Order |
| --- | --- | --- |
| Đang diễn ra | `Active` | 1 (top) |
| Nháp | `Draft` | 2 |
| Đã kết thúc | `Closed`, `Cancelled` | 3 (most recent first within group) |

### 4.4 Roster status filter (monitor tab)

| Control | Options | Default |
| --- | --- | --- |
| `Select` Trạng thái | Tất cả / Có mặt / Vắng / Có phép / Chờ | Tất cả |

Client-side filter on polled data when [FR-15](../brds/03-functional-requirements.md) enabled.

---

## 5. Listing — Sort

### 5.1 Sort interaction

| Pattern | Usage |
| --- | --- |
| Column header click | Toggle asc → desc → default (tables) |
| `Select` dropdown | Mobile narrow tables where headers collapse |
| `aria-sort` | On active column header ([13-accessibility-basics.md](./13-accessibility-basics.md) §7) |

Visual: sort icon (↑↓) on active column; neutral icon on sortable inactive columns.

### 5.2 Default sort orders

| Listing | Default sort | Sortable columns |
| --- | --- | --- |
| `/sessions` | `Active` first, then `scheduledStartTime` desc | — (fixed group order) |
| `/history` | Session date desc | Date only |
| Roster table | `displayName` asc (alphabetical) | Họ tên, MSSV, Trạng thái, Thời gian điểm danh |
| `/admin/users` | `displayName` asc | Họ tên, MSSV, Email, Vai trò |
| Session report table | Session date desc | Ngày, Lớp, Môn, Tỷ lệ có mặt |
| Class roster list | `classCode` asc | Mã lớp, Số sinh viên |

### 5.3 Monitor tab live sort

When instructor sorts roster by status ([AC-15b](../brds/08-acceptance-mvp-future.md)):

| Sort key | Order |
| --- | --- |
| Trạng thái | Chờ → Vắng → Có mặt → Có phép (instructor priority) |
| Họ tên | Locale-aware `vi` collation |

Sort preference stored in session `sessionStorage` per `sessionId` for duration of tab visit.

---

## 6. Listing — Pagination

| Listing | Strategy | Page size |
| --- | --- | --- |
| `/admin/users` | Offset pagination | **25** rows |
| `/history` | Cursor / load more | **20** per fetch ([AC-14a](../brds/08-acceptance-mvp-future.md)) |
| Report tables | Offset pagination | **50** rows |
| Roster (session) | Load all enrolled (**≤ 150**) | Single fetch per [mvpScale](../product-meta.json) |
| `/admin/rosters/:classCode` | Offset pagination | **50** rows |

**Pagination UI:** `Trang {n} / {total}` with **Trước** / **Sau** buttons; disabled at bounds. Current page announced to assistive tech.

**Load more:** Preferred on mobile student history to avoid small tap targets on page numbers.

---

## 7. Listing — Empty and No-Results States

| Condition | Message (vi-VN) | CTA |
| --- | --- | --- |
| No sessions ever | *Chưa có buổi học* | **Tạo buổi học** |
| No history | *Chưa có buổi học nào* | — |
| Search/filter no match | *Không tìm thấy kết quả* | **Xóa bộ lọc** |
| Report before apply | *Chọn bộ lọc và nhấn Áp dụng* | — |
| Report zero rows | *Không có dữ liệu trong khoảng thời gian đã chọn* | Adjust filters |
| Empty class roster | *Lớp chưa có sinh viên* | **Nhập CSV** |

Use `EmptyState` component with illustration optional on desktop only.

---

## 8. Listing — Loading and Refresh

| Behavior | Specification |
| --- | --- |
| Initial load | Full skeleton matching row count (see [12-ui-states.md](./12-ui-states.md)) |
| Filter change | Replace results; show inline spinner in toolbar |
| Background poll (monitor) | No skeleton flash; update row badges in place |
| Stale indicator | *Cập nhật lúc {HH:mm}* subtle text on monitor tab |

Prevent double-fetch: disable **Áp dụng** and search during active request.

---

## 9. Listing — Row Actions and Drill-Down

| Listing | Row click | Row actions |
| --- | --- | --- |
| `SessionCard` | Navigate `/sessions/:id` | — |
| History card | Expand inline detail | — |
| Roster row | — | **Chỉnh sửa** → `AttendanceEditDialog` ([AC-11](../brds/08-acceptance-mvp-future.md)) |
| User row | Navigate `/admin/users/:id` | — |
| Report session row | Drill `/reports/sessions?sessionId=` | — |
| Class row | Navigate `/admin/rosters/:classCode` | — |

Row actions use `IconButton` with `aria-label` or text button on mobile.

---

## 10. Listing — Export Integration

`/admin/export` reuses `ReportFilterBar` filter state model ([FR-13](../brds/03-functional-requirements.md) · [AC-13](../brds/08-acceptance-mvp-future.md)):

| Step | Behavior |
| --- | --- |
| 1 | User configures identical filters as reports |
| 2 | `CsvExportPanel` shows estimated row count from dry-run HEAD request |
| 3 | Export uses same filter query params as report API |

Instructor report listing has **no** export action ([BR-09](../brds/04-business-rules.md)).

---

## 11. Listing — Responsive Behavior

| Breakpoint | Adaptation |
| --- | --- |
| < **768** px | `ReportFilterBar` fields stack vertically; **Áp dụng** full width |
| < **768** px | Admin tables: horizontal scroll; sticky first column (Họ tên) |
| < **768** px | Session list: cards full width |
| ≥ **1024** px | Filter bar inline; table uses full sidebar content width |

Mobile student `/history`: cards only — no table layout.

---

## 12. Listing — API Query Contract

Frontend encodes listing state in query parameters for reproducibility:

| Param | Example | Used on |
| --- | --- | --- |
| `q` | `nguyen` | User search |
| `role` | `Student` | User filter |
| `active` | `true` | User filter |
| `classCode` | `HESD-01` | Reports, rosters |
| `subjectCode` | `SWE-101` | Reports |
| `from` / `to` | ISO date | Reports |
| `page` | `2` | Paginated tables |
| `pageSize` | `25` | Paginated tables |
| `sort` | `displayName` | Tables |
| `order` | `asc` | Tables |
| `status` | `Present` | Roster filter |

Invalid param combinations return **400** with form-level error on report pages.

---

## 13. Listing — Performance

| Target | Requirement | Reference |
| --- | --- | --- |
| Search response | < **500 ms** p95 for admin user search | [NFR-11](../brds/07-non-functional-risk.md) |
| Report load | < **3 s** for 1 semester class | [NFR-07](../brds/07-non-functional-risk.md) |
| Roster load | < **2 s** for **150** rows | Cohort scale |
| Debounced search | Cancel in-flight request on new input | AbortController |

---

## 14. Future Consideration

- Saved filter presets for training office (*HESD kỳ 2026*).
- Bulk actions on roster rows (multi-select checkboxes).
- Full-text search across report notes.
- Virtualized scrolling for rosters beyond **150** students.
- Export listing directly from `/admin/reports` without navigating to `/admin/export`.
