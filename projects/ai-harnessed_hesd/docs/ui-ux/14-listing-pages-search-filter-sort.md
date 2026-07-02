# Attendly — Listing Pages: Search, Filter, Sort, and Pagination

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [09-page-list.md](./09-page-list.md) · [05-common-ui-components.md](./05-common-ui-components.md) · [04-design-tokens.md](./04-design-tokens.md) · [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) · [../technical/05-api-design.md](../technical/05-api-design.md) · [../technical/01-roles-permissions.md](../technical/01-roles-permissions.md)

## 1. Purpose and scope

This document is the **implementation contract** for Attendly listing UX: how search, filter, sort, and pagination behave on every collection route. All privileged and listing routes use `TableToolbar` + `DataTable` per [05-common-ui-components.md](./05-common-ui-components.md) §4. Query parameters align with [05-api-design.md](../technical/05-api-design.md) §2.5.

### 1.1 Mandatory rules

| ID | Rule |
| --- | --- |
| `FR-LST-01` | Every listing route in §0 implements the matrix columns for its page — no partial implementations |
| `FR-LST-02` | `TableToolbar` is **Mandatory** on all admin, lecturer listing, report, and audit routes |
| `FR-LST-03` | Toolbar state syncs with URL query parameters (bookmarkable, shareable) |
| `FR-LST-04` | Filters apply only within role-authorized scope (`BR-18`, `BR-19`) |
| `FR-LST-05` | All listings expose empty, no-result, loading, and error states (`NFR-UI-07`) |
| `NFR-LST-01` | Pagination metadata never exposes cross-scope record counts |

---

## 0. Per-route search / filter / sort / pagination matrix

**Source:** Derived from [09-page-list.md](./09-page-list.md) §7. This matrix is authoritative for frontend and API contract alignment.

Query parameter names (global): `page`, `pageSize`, `sortBy`, `sortOrder`, `search`, `from`, `to`. Defaults: `page=1`, `pageSize=25`, `sortOrder=desc` where noted.

| Page | Route | Search | Filters | Sort fields (`sortBy`) | Pagination |
| --- | --- | --- | --- | --- | --- |
| PG-03 My attendance | `/me/attendance` | — | `termId`, `classSectionId`, `status` | `date` (default desc) | Server: `page`, `pageSize` |
| PG-04 Lecturer sessions | `/lecturer/sessions` | section/session text → `search` | `date`, `state` | `startTime`, `state` | Server: `page`, `pageSize` |
| PG-06 Live roster | `/lecturer/sessions/{id}/roster` | student name/code → `search` | `status`, `attemptOutcome` | `status`, `checkInTime` | Client virtualized; single session scope |
| PG-07 Terms | `/admin/terms` | term name/code → `search` | `active` (boolean) | `startDate`, `name` | Server: `page`, `pageSize` |
| PG-08 Courses | `/admin/courses` | course name/code → `search` | `facultyId` | `code`, `name` | Server: `page`, `pageSize` |
| PG-09 Class sections | `/admin/class-sections` | section code → `search` | `termId`, `courseId`, `lecturerUserId` | `sectionCode`, `termId` | Server: `page`, `pageSize` |
| PG-10 Enrollments | `/admin/class-sections/{id}/enrollments` | student name/code → `search` | `enrollmentStatus` | `studentCode` | Server: `page`, `pageSize` |
| PG-11 Rooms | `/admin/rooms` | room/building name → `search` | `building`, `gpsEnabled` | `name`, `building` | Server: `page`, `pageSize` |
| PG-12 Policies | `/admin/policies` | scope name → `search` | `scopeLevel` | `scopeLevel`, `updatedAt` | Server: `page`, `pageSize` |
| PG-13 Reports | `/reports/attendance` | student name/code → `search` | `termId`, `classSectionId`, `courseId`, `lecturerUserId`, `status`, `from`, `to` | `date`, `status`, `classSectionId` | Server: `page`, `pageSize` |
| PG-15 Audit logs | `/audit/logs` | actor/target text → `search` | `actorUserId`, `targetType`, `actionType`, `from`, `to` | `timestamp` (default desc) | Server: `page`, `pageSize` |

**Matrix notes:**

- **Search** — case-insensitive normalized text within authorized scope; empty `search` returns full scoped set (`FR-TTB-01`).
- **Filters** — render as active chips with per-chip remove and clear-all (`FR-TTB-02`).
- **Sort** — visible column header or dropdown; `sortOrder` toggles `asc`/`desc` (`FR-TTB-03`); only allow-listed `sortBy` values accepted server-side.
- **Pagination** — `pageSize` default `25`, max `100`; show "Showing X–Y of Z" where Z is scoped count only (`NFR-LST-01`).

---

## 2. `TableToolbar` specification

### 2.1 Layout regions

| Region | Position | Contents |
| --- | --- | --- |
| Left | Start | **Search** input with clear button |
| Center | Middle | Filter dropdowns, date range pickers, status selectors |
| Right | End | Sort control, primary contextual actions (`Tạo mới`, `Xuất CSV`) |

On narrow viewports, regions wrap: Search full width → filters row → actions row. No control becomes unreachable (`NFR-LAY-02`).

### 2.2 Search behavior

| Aspect | Specification |
| --- | --- |
| Debounce | 300 ms after last keystroke before API call |
| Trigger | Also applies on `Enter` immediately |
| Clear | `×` button resets `search` param and refetches |
| Scope | Search never widens beyond role authorization |
| Empty query | Omits `search` param; returns default scoped list |
| Placeholder | Descriptive per route (e.g. "Tìm MSSV hoặc tên..." on PG-13) |

`FR-TTB-01`: Search updates table query state and supports reset.

### 2.3 Filter behavior

| Aspect | Specification |
| --- | --- |
| Chip display | Each active filter shows label + value as removable chip |
| Clear all | Single "Xóa bộ lọc" action resets all filters and search |
| URL sync | Each filter maps to a query param (`FR-TTB-05`) |
| Dependent filters | Section filter options constrained by selected term (PG-13) |
| Date range | `from` / `to` ISO date; invalid range shows inline error |

`FR-TTB-02`: Filters show active-state chips and clear-all option.

### 2.4 Sort behavior

| Aspect | Specification |
| --- | --- |
| Default sort | Per matrix §0 column (e.g. `timestamp desc` on PG-15) |
| UI control | Column header click or explicit sort dropdown on mobile |
| Indicator | Arrow icon + `aria-sort` on active column |
| Toggle | First click sets `sortBy`; subsequent toggles `sortOrder` |
| Invalid field | Server ignores unknown `sortBy`; UI restricts to allow-list |

`FR-TTB-03`: Sort state is visible and reversible.

### 2.5 Contextual actions

| Action | Routes | Permission gate |
| --- | --- | --- |
| Create (`Tạo mới`) | PG-07–PG-09, PG-11, PG-12 | `AcademicAdmin` / scoped `DepartmentAdmin` |
| Export CSV | PG-13 | Lecturer (scoped), `DepartmentAdmin`, `AcademicAdmin` |
| Import CSV | PG-10 | `AcademicAdmin`, scoped `DepartmentAdmin` |

`FR-TTB-04`: Actions are role-scoped and disabled/hidden when unauthorized.

---

## 3. Pagination specification

### 3.1 Server pagination (default)

| Parameter | Value |
| --- | --- |
| `page` | 1-based index |
| `pageSize` | Default `25`; user-selectable `10`, `25`, `50`, `100` |
| Max `pageSize` | `100` for interactive lists |

UI components: [pagination.md](./design-system/pagination.md).

| Element | Behavior |
| --- | --- |
| Range label | "Hiển thị 1–25 trong 142 kết quả" (scoped count) |
| Prev/Next | Disabled at boundaries |
| Page numbers | Show current ±2 pages with ellipsis for gaps |
| Page size selector | Updates `pageSize` and resets to `page=1` |

### 3.2 Client virtualized pagination (PG-06 only)

Live roster for a single session uses in-memory virtualization — no server `page` param. Search/filter/sort apply client-side over the enrolled set. Pagination control hidden; scroll loads rows via virtual window.

---

## 4. Per-route implementation notes

### 4.1 PG-03 — Student attendance history

- Mobile-first: filters collapse to bottom sheet on narrow viewports.
- No export button (`FR-37`).
- Default sort: `date desc` (most recent first).

### 4.2 PG-04 — Lecturer sessions

- Default filter: `date=today` on first visit (convenience, overridable).
- State filter chips: `Scheduled`, `Open`, `Closed`, `Cancelled`.
- Row primary action: navigate to PG-05 or PG-06 based on state.

### 4.3 PG-06 — Live roster

- Count summary chips above table update with filter scope.
- `attemptOutcome` filter surfaces rejected check-in rows.
- Realtime updates preserve active search/filter (`NFR-UI-06`).

### 4.4 PG-07–PG-12 — Admin listings

- Rich filter sets per matrix §0.
- Create action opens modal form (FRM-02–FRM-07).
- Empty state includes create CTA for authorized roles.

### 4.5 PG-13 — Attendance reports

- Broadest filter set; `ExportScopeSummary` reflects active toolbar state before export.
- Date range `from`/`to` required for large exports (warning if unbounded).
- `DepartmentAdmin` filters auto-scoped to assigned faculty.

### 4.6 PG-15 — Audit logs

- Default sort: `timestamp desc`.
- `actionType` filter: check-in, edit, export, login events.
- Read-only; no row mutation actions.

---

## 5. Listing page states

Every route in §0 implements these states (`NFR-UI-07`):

| State | Condition | UI |
| --- | --- | --- |
| `loading` | Fetch in progress | Table skeleton; toolbar remains interactive |
| `empty` | Zero records in scope | Message + setup CTA if applicable |
| `no-results` | Filters/search match nothing | "Không tìm thấy kết quả" + clear filters |
| `error` | API failure | `FeedbackAlert` + retry |
| `list` | Data present | `DataTable` + pagination |

See [12-ui-states.md](./12-ui-states.md) §6 for state IDs and transitions.

---

## 6. API and URL synchronization

### 6.1 URL query contract

Example — PG-13:

```
/reports/attendance?termId=hk2026&classSectionId=cs101-a&status=Absent&from=2026-02-01&to=2026-02-28&sortBy=date&sortOrder=desc&page=2&pageSize=25&search=20100
```

| Event | URL behavior |
| --- | --- |
| Filter change | Update param; reset `page=1` |
| Search change | Update `search`; reset `page=1` |
| Sort change | Update `sortBy`/`sortOrder`; keep `page` unless invalid |
| Page change | Update `page` only |
| Browser back | Restore toolbar + table from URL |

`FR-TTB-05`: Toolbar state syncs with route query params.

### 6.2 Authorization interaction

- API applies role scope **before** filters (`BR-19`).
- UI never displays filter options for out-of-scope entities.
- Unauthorized direct URL → permission empty state, not partial data (`AC-UI-09`).

---

## 7. Token and component references

| UI element | Design module | Token mapping |
| --- | --- | --- |
| Search input | [inputs.md](./design-system/inputs.md) | `--input-border`, `--input-focus-ring` |
| Filter chips | [badges.md](./design-system/badges.md) | `--badge-neutral`, removable button |
| Sort headers | [tables.md](./design-system/tables.md) | `--table-header-bg` |
| Pagination | [pagination.md](./design-system/pagination.md) | `--pagination-active` |
| Empty state | [content.md](./design-system/content.md) | `--text-muted` |

Full token map: [04-design-tokens.md](./04-design-tokens.md) §0.

---

## 8. Traceability

| Listing concern | Requirement links |
| --- | --- |
| Consistent toolbar | `FR-OV-05`, `FR-TTB-01`–`FR-TTB-05`, `AC-UI-07` |
| Scope-safe filtering | `FR-27`, `FR-28`, `FR-32`, `BR-18`, `BR-19` |
| Export scope | `FR-27`, `AC-UI-08`, `AC-15`–`AC-17` |
| Empty/error resilience | `NFR-UI-07`, `FR-OV-07` |
| API alignment | [05-api-design.md](../technical/05-api-design.md) §2.5 |

---

## 9. Future consideration

- Saved filter presets per role (e.g. lecturer "my sections today").
- Column visibility picker on wide report tables.
- Server-side cursor pagination for audit logs exceeding 100k entries.
- Bulk actions on admin listings with selection checkboxes and preview modal.
