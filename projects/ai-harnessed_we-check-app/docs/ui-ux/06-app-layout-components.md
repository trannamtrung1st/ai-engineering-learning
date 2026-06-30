# We Check — App Layout Components

Role-based application shells and page scaffolding for **We Check** MVP. Layout components wrap routes and provide consistent navigation, headers, and content regions.

**Related documents:** [UI framework](./02-ui-framework-tech-stack.md) · [Common components](./05-common-ui-components.md) · [Design overview](./01-design-overview.md) · [01-roles-permissions.md](../technical/01-roles-permissions.md)

---

## 1. Layout

Layout components live in `apps/web/src/components/layout/`. Each role has a dedicated shell that enforces navigation scope, header content, and responsive behavior. Pages supply content via `children` or React Router `<Outlet />`.

---

## 2. Layout Hierarchy

```mermaid
flowchart TB
    Root[RootLayout — providers, error boundary]
    Auth[AuthLayout — login/unauthenticated]
    Student[StudentLayout]
    Instructor[InstructorLayout]
    Admin[AdminLayout]
    Fullscreen[FullscreenLayout — QR presentation]

    Root --> Auth
    Root --> Student
    Root --> Instructor
    Root --> Admin
    Instructor --> Fullscreen
```

---

## 3. RootLayout

| Responsibility | Detail |
| --- | --- |
| Error boundary | Catches render errors; shows Vietnamese fallback with reload |
| Outlet | Renders child route layout |
| Skip link | “Bỏ qua đến nội dung chính” for keyboard users |
| Document title | `We Check — {page title}` via route handle |

No navigation chrome at root level.

### 3.1 ShellOverview and route discovery

Unauthenticated visitors at `/` see `ShellOverviewPage` — a component showcase plus a **route discovery** section. Authenticated users never see this page; `RoleHomeRedirect` sends them to role home per [AC-18e](../brds/08-acceptance-mvp-future.md) ([FR-18](../brds/03-functional-requirements.md)).

| Element | Specification |
| --- | --- |
| Placement | Below showcase content (badges, QR countdown, outcome panels) |
| Section heading | *Đi tới trang* (`--font-display`, `--text-h2`) |
| Component | `RouteDiscoveryPanel` — grouped quick links reusing `NavCard` / `QuickActionGrid` styling from `RoleHomeHub` |
| Links (unauthenticated only) | **Đăng nhập** → `/login`; **Điểm danh** → `/check-in`; **Buổi học** → `/sessions`; **Quản trị** → `/admin` |
| Protected targets | Auth guard redirects to `/login?returnUrl=…` per [BR-06](../brds/04-business-rules.md); discovery links are entry points, not permission-gated chrome |
| Visibility | Hidden when session exists ([AC-18g](../brds/08-acceptance-mvp-future.md)) |
| Test IDs | `data-testid="route-discovery-panel"` on container; `data-testid="route-discovery-{slug}"` per link (`login`, `check-in`, `sessions`, `admin`) |

**Wireframe:** [11-wireframes.md](./11-wireframes.md) §14.3.

---

## 4. AuthLayout

Used for `/login` and password recovery (if added).

### 4.1 Desktop (≥768 px) — split panel

```
┌──────────────────┬──────────────────┐
│ Navy brand panel │ Login card       │
│ (hero-band-dark) │ (--shadow-lg,    │
│ Product name +   │  max 400 px)     │
│ subtitle         │ Form (Outlet)    │
└──────────────────┴──────────────────┘
```

| Region | Specification |
| --- | --- |
| Brand panel | Solid `--color-brand-700` (`colors.brand-navy`); Inter semibold product name; `--color-text-inverse` copy — DESIGN.md `hero-band-dark` |
| Login card | Centered, max-width **400 px**, `--shadow-lg`, `--radius-lg` |
| Primary submit | `button-primary` — `--color-primary-600` purple CTA |
| Background | `--color-surface-default` (warm gray) |

### 4.2 Mobile (<768 px)

Single centered card (same as prior spec): max-width **400 px**, `--space-4` padding, `--shadow-md`.

| Region | Specification |
| --- | --- |
| Header | We Check product name (`--font-display`) + subtitle “Điểm danh số cho buổi học” |
| Background | `--color-surface-default` |
| Footer | Institutional support line (optional text link); optional *Quay về trang chủ* → `/` on `/login` ([FR-18](../brds/03-functional-requirements.md)) |

**Behavior:** Redirect authenticated users to role home ([FR-02](../brds/03-functional-requirements.md)). Preserve `returnUrl` query for post-login check-in deep link ([BR-06](../brds/04-business-rules.md)).

---

## 5. StudentLayout

Mobile-first shell for `Student` role routes: `/check-in`, `/history`.

### 5.1 Structure

```
┌─────────────────────────────┐
│ AppHeader (compact, white)  │
├─────────────────────────────┤
│  warm gray background       │
│   PageContent (Outlet)      │
│                             │
├─────────────────────────────┤
│ BottomNav (pill active)     │
└─────────────────────────────┘
```

Page content area uses `--color-surface-default`; cards inside use `--color-surface-raised` with `--shadow-sm`.

### 5.2 AppHeader (student variant)

| Element | Content |
| --- | --- |
| Left | We Check logo text (links to `/check-in`) |
| Right | `UserMenu` — identity panel + logout (data from `/auth/me`) |

Height: **56 px**. Sticky top.

### 5.3 BottomNav

Items filtered by `usePermittedNav()` — only routes the student holds `checkin:submit` or `attendance:read` (self) for are rendered. Items the user lacks are **omitted** from DOM ([BR-14](../brds/04-business-rules.md)).

| Item | Route | Required permission | Icon |
| --- | --- | --- | --- |
| Điểm danh | `/check-in` | `checkin:submit` | `QrCode` |
| Lịch sử | `/history` | `attendance:read` (self) | `History` |

On `/check-in` when idle (no active scan), show `RoleHomeHub` student variant with cards **Quét mã điểm danh** and **Xem lịch sử** above the scan entry point.

Hidden on `/check-in` when camera active (scan step) to maximize viewfinder.

### 5.4 PageContent

- Horizontal padding: `--space-4`
- Max-width: **480 px**, centered
- Min-height: fills viewport minus header/nav

### 5.5 Student layout rules

- No sidebar.
- Primary actions fixed bottom on long forms (safe-area inset for iOS).
- Student never sees instructor or admin navigation items.

---

## 6. InstructorLayout

Desktop-primary shell for `/sessions/*` and instructor reports.

### 6.1 Structure

```
┌──────────┬──────────────────────────────────┐
│          │ TopBar — breadcrumb, UserMenu    │
│ Sidebar  ├──────────────────────────────────┤
│          │                                  │
│  Nav     │   PageContent (Outlet)           │
│          │                                  │
└──────────┴──────────────────────────────────┘
```

### 6.2 Sidebar

`SidebarNav` filters items via `usePermittedNav()` per [01-roles-permissions.md](../technical/01-roles-permissions.md) §2.3a. Unauthorized items are **not rendered** (not disabled).

| Item | Route | Required permission | Icon |
| --- | --- | --- | --- |
| Buổi học | `/sessions` | `session:read` | `Calendar` |
| Báo cáo | `/reports` | `report:read` | `BarChart3` |

On `/sessions`, render instructor `RoleHomeHub` above the session list: cards **Tạo buổi học mới**, **Buổi học của tôi**, **Báo cáo điểm danh**; active-session shortcut when one exists.

Width: **240 px** on `lg+`; collapses to icon rail on `md`; drawer overlay on `< md`.

Active item: `--color-primary-50` background, `--color-primary-600` text, `--radius-md` pill shape. Hairline `--color-border-default` between nav groups. Density follows Notion sidebar rhythm (compact 36–40 px row height, `--space-3` horizontal inset) per [`design-craft-notion` skill](../../ai-harness/skills/design-craft-notion/SKILL.md) — **exactly one** active item per layout ([BR-14a](../brds/04-business-rules.md)).

#### 6.2a Active nav route matching

Enforces singleton active indicator ([BR-14a](../brds/04-business-rules.md), [AC-18h](../brds/08-acceptance-mvp-future.md), [AC-18i](../brds/08-acceptance-mvp-future.md)). Each nav descriptor carries `match: "exact" | "prefix"` (default `prefix`). Map to React Router `NavLink` `end` prop: `exact` → `end={true}`; `prefix` → `end={false}` unless a more specific sibling item matches.

**Student bottom nav**

| Current path | Active item | Match |
| --- | --- | --- |
| `/check-in`, `/check-in/*` | Điểm danh | prefix |
| `/history` | Lịch sử | exact |

**Instructor sidebar**

| Current path | Active item | Match |
| --- | --- | --- |
| `/sessions`, `/sessions/new`, `/sessions/:id`, `/sessions/:id/*` | Buổi học | prefix |
| `/reports`, `/reports/*` | Báo cáo | prefix |

**Admin sidebar** — see §7.2 for item list; matching table:

| Current path | Active item | Match |
| --- | --- | --- |
| `/admin` | Trang chủ | exact |
| `/admin/users`, `/admin/users/*` | Người dùng | prefix |
| `/admin/classes`, `/admin/classes/new` | Lớp học | prefix |
| `/admin/subjects`, `/admin/subjects/new` | Môn học | prefix |
| `/admin/rosters`, `/admin/rosters/:classCode` | Danh sách ghi danh | prefix with `end` on `/admin/rosters` only — **exclude** `/admin/rosters/import` |
| `/admin/rosters/import` | Nhập danh sách | exact |
| `/admin/reports`, `/admin/reports/*` | Báo cáo | prefix |
| `/admin/export`, `/admin/export/*` | Xuất CSV | prefix |
| `/admin/policy`, `/admin/policy/*` | Chính sách | prefix |

When two items could match by prefix, the **longest matching route** wins; parent prefix items must not remain active.

### 6.3 TopBar

- Breadcrumb from route handle
- Session `StatusBadge` when inside active session route
- `UserMenu` right-aligned — identity panel + logout (data from auth context / `/auth/me`)

Height: **64 px**. Sticky.

### 6.4 PageContent

- Padding: `--space-6` on desktop, `--space-4` on mobile
- Max-width: **1280 px** for tables

### 6.5 Responsive behavior

| Breakpoint | Sidebar |
| --- | --- |
| `< md` | Hamburger opens `Sheet` drawer |
| `md – lg` | Collapsed icon rail |
| `≥ lg` | Full sidebar |

---

## 7. AdminLayout

Shell for `TrainingOfficeAdmin` routes under `/admin/*`.

### 7.1 Structure

Same grid as `InstructorLayout` with expanded navigation.

### 7.2 Sidebar

`SidebarNav` uses `usePermittedNav()` — items without required permission are omitted ([BR-14](../brds/04-business-rules.md)). Active-state matching per §6.2a ([BR-14a](../brds/04-business-rules.md)).

| Item | Route | Required permission | Match | Icon |
| --- | --- | --- | --- | --- |
| Trang chủ | `/admin` | any admin read permission | exact | `Home` |
| Người dùng | `/admin/users` | `user:read` (all) | prefix | `Users` |
| Lớp học | `/admin/classes` | `roster:read` (all) | prefix | `GraduationCap` |
| Môn học | `/admin/subjects` | `roster:read` (all) | prefix | `BookOpen` |
| Danh sách ghi danh | `/admin/rosters` | `roster:read` (all) | prefix† | `List` |
| Nhập danh sách | `/admin/rosters/import` | `roster:write` | exact | `Upload` |
| Báo cáo | `/admin/reports` | `report:read` (institution) | prefix | `BarChart3` |
| Xuất CSV | `/admin/export` | `report:export` | prefix | `Download` |
| Chính sách | `/admin/policy` | `policy:write` | prefix | `Settings` |

† `/admin/rosters` uses `end={true}` so `/admin/rosters/import` does not co-highlight this item.

Create actions for class and subject catalogs live on list-page CTAs (**Thêm lớp**, **Thêm môn**) — not as separate sidebar entries.

Default post-login landing: `/admin` hub (`RoleHomeHub`), not `/admin/users` unless deep-linked.

### 7.3 Admin-specific chrome

- “Quản trị” label in sidebar header to distinguish from instructor view.
- Export and policy routes show compliance reminder footer on destructive actions.

### 7.4 Access control

If non-admin hits `/admin/*`, render **403 Forbidden** page inside `RootLayout` (no admin nav leaked).

---

## 8. FullscreenLayout

Used for instructor QR presentation ([FR-06](../brds/03-functional-requirements.md), [NFR-20](../brds/07-non-functional-risk.md)).

| Region | Specification |
| --- | --- |
| Background | `--color-qr-bg` (black) |
| Header strip | Session title, room, `StatusBadge` `Active` — `--color-text-inverse` |
| Main | Centered QR image + countdown (`text-display`) |
| Footer | “Thoát toàn màn hình” ghost button; last-updated timestamp |
| Chrome | No sidebar; minimal UI |

Enter via “Trình chiếu QR” on session detail. Uses Fullscreen API when available.

**Countdown colors:** `--color-qr-accent` > 10 s; `--color-qr-warning` ≤ 10 s.

---

## 9. Page Scaffolding Components

### 9.1 PageHeader

| Prop | Type | Description |
| --- | --- | --- |
| `title` | string | Vietnamese page title |
| `description` | string | Optional subtitle |
| `actions` | ReactNode | Right-aligned button group |
| `backTo` | string | Optional back link |

Used on list and detail pages across roles.

### 9.2 PageContent

Wraps outlet body with consistent padding and max-width. Props: `variant` (`narrow` \| `default` \| `wide`).

| Variant | Max width |
| --- | --- |
| `narrow` | 480 px (student) |
| `default` | 720 px (forms) |
| `wide` | 1280 px (tables) |

### 9.3 SplitView

Optional two-column layout for session editor: form left, map preview right on `lg+`. Stacks on mobile.

### 9.4 ForbiddenPage

Static **403** content: title “Không có quyền truy cập”, message per [BR-08](../brds/04-business-rules.md), link back to home.

### 9.5 NotFoundPage

**404** for unknown routes with link to role home.

---

## 10. Route-to-Layout Mapping

| Route pattern | Layout | Role |
| --- | --- | --- |
| `/login` | `AuthLayout` | Public |
| `/check-in`, `/check-in/*` | `StudentLayout` | `Student` |
| `/history` | `StudentLayout` | `Student` |
| `/sessions`, `/sessions/:id`, `/sessions/:id/*` | `InstructorLayout` | `Instructor` |
| `/sessions/:id/qr-present` | `FullscreenLayout` | `Instructor` |
| `/reports`, `/reports/*` | `InstructorLayout` | `Instructor` |
| `/admin/*` | `AdminLayout` | `TrainingOfficeAdmin` |

Router guard redirects wrong role to appropriate home or `ForbiddenPage`.

---

## 11. Session Detail Layout (Instructor)

Nested layout inside `InstructorLayout` for `/sessions/:id`:

```
PageHeader — session title, StatusBadge, actions (Mở/Đóng buổi học)
Tabs — QR | Theo dõi | Danh sách | Cài đặt
Tab content (Outlet)
```

| Tab | Content |
| --- | --- |
| QR | QR preview + “Trình chiếu QR” launches `FullscreenLayout` |
| Theo dõi | `StatCard` row + polling roster ([FR-15](../brds/03-functional-requirements.md)) |
| Danh sách | Full `DataTable` with manual edit actions ([FR-11](../brds/03-functional-requirements.md)) |
| Cài đặt | Session metadata edit (only in `Draft`) |

When session `Active`, default tab is **Theo dõi**; when `Draft`, default is **Cài đặt**.

---

## 12. Live Region and Polling Chrome

Instructor session tabs show subtle status bar:

- “Cập nhật lúc HH:mm:ss” when poll succeeds
- “Không thể cập nhật — thử lại” with retry when poll fails
- Does not block QR display

---

## 13. Traceability

| Layout | FR | NFR | AC |
| --- | --- | --- | --- |
| `StudentLayout` + check-in | FR-07, FR-08 | NFR-18 | AC-07, AC-08 |
| `FullscreenLayout` | FR-06 | NFR-20 | AC-06 |
| `InstructorLayout` monitor | FR-15 | — | AC-15 |
| `AdminLayout` export | FR-13 | NFR-11 | AC-13 |
| `AuthLayout` | FR-02 | NFR-16 | AC-02 |
| `ForbiddenPage` | FR-12 | NFR-11 | AC-12 |

---

## 14. Future Consideration

- Collapsible sidebar user preference persistence.
- Instructor multi-session switcher in TopBar.
- Print stylesheet for attendance reports.
- `ITOperations` read-only status dashboard layout (separate ops portal).
