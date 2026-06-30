# We Check — Common UI Components

Shared primitive and compound components for **We Check** MVP. All feature screens compose from this catalog before adding domain-specific widgets.

**Related documents:** [Design system basics](./03-design-system-basics.md) · [Design tokens](./04-design-tokens.md) · [App layout components](./06-app-layout-components.md) · [Event-specific components](./07-event-specific-components.md) (downstream)

---

## 1. Component

Components live under `apps/web/src/components/ui/` (primitives) and `apps/web/src/components/shared/` (compositions). Each wraps Radix UI where noted and applies tokens from [04-design-tokens.md](./04-design-tokens.md).

**Import rule:** Feature modules import from `@/components/ui` and `@/components/shared` only — not directly from `@radix-ui/*`.

---

## 2. Primitive Components (`components/ui/`)

### 2.1 Button

| Prop | Values | Notes |
| --- | --- | --- |
| `variant` | `primary`, `secondary`, `outline`, `ghost`, `danger` | Maps to token colors |
| `size` | `sm`, `md`, `lg` | `md` default; min height `--size-touch-min` on mobile student routes |
| `loading` | boolean | Shows spinner; disables click |
| `disabled` | boolean | `aria-disabled`; reduced opacity |

**Visual (Notion — `button-primary`, `button-secondary`, `button-ghost`):**

Foreground/background pairs must match [04-design-tokens.md](./04-design-tokens.md) §3.2.1:

| `variant` | Background | Label / foreground |
| --- | --- | --- |
| `primary` | `--color-primary-600` (hover `--color-primary-700`) | `--color-primary-foreground` |
| `secondary` | `--color-surface-raised` + `--color-border-default` border | `--color-text-primary` |
| `outline` | transparent | `--color-primary-600` text and border |
| `ghost` | transparent | `--color-text-primary` |
| `danger` | `--color-danger-500` | `--color-text-inverse` |
| `disabled` | `--color-surface-muted` | `--color-text-disabled` (≥ 3:1) |

- `primary`: `--radius-md` (8 px), `--shadow-sm`, hover `--shadow-md` — DESIGN.md rectangular buttons, not pills
- Active press: `scale(0.98)` for `--duration-fast` unless reduced motion
- Focus: `--focus-ring-*` tokens

**Size padding** (per [04-design-tokens.md](./04-design-tokens.md) §5.1):

| `size` | Horizontal | Vertical inset |
| --- | --- | --- |
| `sm` | `--space-3` | `--space-2` |
| `md` | `--space-4` | min-height `--size-touch-min` |
| `lg` | `--space-5` | `--space-4` |

**Not acceptable:** light text on `--color-primary-500` without verified contrast; disabled opacity so low label drops below **3:1**; icon-only buttons smaller than **44×44 px** on student routes.

**Usage:** Primary CTA “Điểm danh”, “Mở buổi học”; `danger` for “Hủy buổi học”.

### 2.2 IconButton

Square button with Lucide icon only. **Required:** `aria-label` in Vietnamese.

### 2.3 Input

Text, email, password, number types. Features: label slot, error text, `aria-invalid`, `aria-describedby` for hints.

### 2.4 Textarea

Multi-line input for manual edit reason ([BR-10](../brds/04-business-rules.md)). Auto-grow optional.

### 2.5 Select

Radix `Select`. Vietnamese labels for options. Used for role assignment, status filters.

### 2.6 Checkbox / Switch

Radix primitives. Switch for admin active-user toggle; checkbox for bulk roster selection (future).

### 2.7 Label

Radix `Label` associated with control `id`.

### 2.8 Card

| Part | Element |
| --- | --- |
| `Card` | Container with `--shadow-sm`, `--radius-md`, `--color-surface-raised` on `--color-surface-default` pages |
| `CardHeader` | Title in `--font-display`; optional actions |
| `CardContent` | Body padding `--space-4` |
| `CardFooter` | Actions row |

**Visual:** Desktop hover promotes to `--shadow-md` with `translateY(-1px)`. Data table cards use `--shadow-md` by default.

### 2.9 Badge

Static pill for counts and metadata. Variants: `default`, `outline`.

### 2.10 StatusBadge

Maps `SessionStatus` and `AttendanceStatus` enums to token colors ([04-design-tokens.md](./04-design-tokens.md) §12).

| Prop | Type |
| --- | --- |
| `status` | `AttendanceStatus` \| `SessionStatus` |
| `size` | `sm` \| `md` |

**Visual:** Rounded pill (`--radius-full`), semantic wash background, semibold label in `--font-sans`. Session `Active` uses success tokens with subtle pulse on instructor monitor only.

Always includes Vietnamese label text from [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) §2.

### 2.11 Alert

Inline banner. Variants: `info`, `success`, `warning`, `danger`. Optional icon and dismiss.

Used for: GPS consent, session closed notice, import errors.

### 2.12 Dialog

Radix `Dialog`. Standard structure:

- `DialogTitle` — verb + object (“Xác nhận hủy buổi học”)
- `DialogDescription` — consequence text
- `DialogFooter` — cancel (secondary) + confirm (primary/danger)

Focus trap and Escape close required.

### 2.13 DropdownMenu

Row actions menu (⋮). Items: icon + label. Destructive item uses `danger` text color.

### 2.14 Tabs

Radix `Tabs` for session detail views: “QR”, “Theo dõi”, “Danh sách”.

### 2.15 Tooltip

Radix `Tooltip` for icon-only controls and GPS radius help on session form.

### 2.16 Toast

Sonner or Radix Toast. Vietnamese message from API `errorCode` mapping. Duration **4 s** default; errors persist until dismiss.

### 2.17 Spinner / LoadingOverlay

| Component | Use |
| --- | --- |
| `Spinner` | Inline button/table loading |
| `LoadingOverlay` | Full-card blocking fetch |
| `Skeleton` | Table rows, session list placeholders |

### 2.18 EmptyState

| Prop | Description |
| --- | --- |
| `icon` | Lucide icon |
| `title` | Vietnamese heading |
| `description` | Optional helper text |
| `action` | Optional `Button` CTA |

### 2.19 ErrorState

Full-region error with message, retry button, and optional support hint. Used when query fails.

### 2.20 Role home components (`components/layout/`)

#### `RoleHomeHub`

Permission-filtered quick-link grid on role home routes ([FR-18](../brds/03-functional-requirements.md)). Props: `role`, `permissions[]`, optional `activeSessionId` (instructor). Cards without permission are **omitted** ([BR-14](../brds/04-business-rules.md)).

#### `NavCard`

Single hub card: `title`, optional `description`, `href`, Lucide `icon`, `data-testid`. Min touch target **44×44 px**.

#### `QuickActionGrid`

Responsive grid wrapping `NavCard` children: 1 col mobile, 2 cols `md+`, 3 cols admin `lg+`.

#### `RouteDiscoveryPanel`

Chrome-less route discovery for unauthenticated `/` ([FR-18](../brds/03-functional-requirements.md), [AC-18f](../brds/08-acceptance-mvp-future.md)). Renders below `ShellOverviewPage` showcase content.

| Prop | Type | Description |
| --- | --- | --- |
| `links` | `RouteDiscoveryLink[]` | Ordered list of entry-point links |
| `links[].to` | `string` | React Router path (e.g. `/login`, `/check-in`) |
| `links[].label` | `string` | Vietnamese link title (e.g. **Đăng nhập**) |
| `links[].description` | `string?` | Optional one-line hint under title |
| `links[].roleHint` | `string?` | Optional role label (e.g. *Sinh viên*, *Giảng viên*) |
| `links[].testId` | `string` | `data-testid` slug for e2e |

Reuses `NavCard` visual treatment from `RoleHomeHub`. Not permission-filtered — auth guard handles protected routes. Hidden when user is authenticated ([AC-18g](../brds/08-acceptance-mvp-future.md)).

---

## 3. Form Components (`components/shared/form/`)

### 3.1 Form

React Hook Form provider wrapper with Zod resolver from `@wecheck/domain`.

### 3.2 FormField

Connects `name`, `label`, `description`, `error` to child input. Displays Zod error in Vietnamese.

### 3.3 FormActions

Sticky footer on mobile with primary submit and secondary cancel. Submit shows loading state.

### 3.4 FieldError

Standalone error text for non-form contexts.

**Details:** [08-forms-validation-ux.md](./08-forms-validation-ux.md) (downstream).

---

## 4. Data Display Components (`components/shared/data/`)

### 4.1 DataTable

TanStack Table wrapper.

| Feature | MVP |
| --- | --- |
| Sorting | Client or server (admin lists: server) |
| Pagination | Server-side for rosters > 50 rows |
| Loading | Skeleton rows |
| Empty | `EmptyState` |
| Row selection | Optional for admin bulk (future) |

### 4.2 TableToolbar

Database-style filter row for listing pages ([14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) §0). Implements DESIGN.md `search-pill` + filter chips per [`design-craft-notion` skill](../../ai-harness/skills/design-craft-notion/SKILL.md).

| Slot | Spec |
| --- | --- |
| Search | Left-aligned; min width 200 px desktop; full width mobile stack |
| Filters | `Select` chips or dropdowns; gap `--space-2` |
| Sort | Column header sort or toolbar `Select` when card layout |
| Primary action | Right-aligned CTA (e.g. **Thêm lớp**, **Xuất CSV**) |
| Padding | Toolbar inset `--space-4`; gap between controls `--space-3` |
| Surface | `--color-surface-elevated` card above table; hairline `--color-border-subtle` below toolbar |

Every listing in [14-listing-pages](./14-listing-pages-search-filter-sort.md) §0 must expose search, filter, sort, and pagination (or documented variant).

### 4.3 TablePagination

“Trang X / Y”; prev/next; page size select (25, 50, 100).

### 4.4 DescriptionList

Key-value pairs for session detail sidebar (room, time, radius).

### 4.5 StatCard

Numeric summary with label — used on live monitor (đã điểm danh / chưa / vắng).

---

## 5. Feedback and Permission Components

### 5.1 ConfirmDialog

Preset dialog for destructive confirms. Props: `title`, `description`, `confirmLabel`, `onConfirm`, `variant`.

### 5.2 PermissionGuideModal

Platform-specific steps for camera or GPS enable ([NFR-19](../brds/07-non-functional-risk.md)).

| Prop | Values |
| --- | --- |
| `type` | `camera` \| `gps` |
| `platform` | `ios` \| `android` \| `unknown` |

Content blocks per [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) §8.

### 5.3 CheckInOutcomePanel

**Signature element** — Notion pastel check-in outcome moment ([01-design-overview.md](./01-design-overview.md) §5.5).

Displays check-in result with distinct visual treatment per outcome: hero icon, semibold headline, body message, card-tint pastel wash, and single purple recovery CTA.

| Element | Specification |
| --- | --- |
| Container | Full-width within page content; `--radius-lg`; `--shadow-md`; padding `--space-6` |
| Icon | `--size-icon-lg` (32 px) Lucide icon per [04-design-tokens.md](./04-design-tokens.md) §13 |
| Headline | Inter semibold, `--text-h1-size` |
| Wash | Background from outcome token mapping (`success-50`, `warning-50`, etc.) |
| CTA | Single primary `Button`; min height `--size-touch-min` |
| Motion | Reveal with scale 0.98→1 + opacity (`--duration-slow`, `--ease-spring`); disabled when reduced motion |

Maps all `CheckInOutcome` values from [01-ui-ux-foundation.md](./01-ui-ux-foundation.md) §2.3. Token mapping: [04-design-tokens.md](./04-design-tokens.md) §13.

---

## 6. Navigation Components

### 6.1 NavLink

Router-aware link with active styles (`--color-primary-50` background, `--color-primary-600` text, `font-medium`) — DESIGN.md `pill-tab-active` equivalent for nav.

When active, set `aria-current="page"`. Nav descriptors may carry optional `match: "exact" | "prefix"` (default `prefix`); map to React Router `end` prop — `exact` → `end={true}`, `prefix` → `end={false}`. Singleton active state per layout is enforced by route matrix in [06-app-layout-components.md](./06-app-layout-components.md) §6.2a ([BR-14a](../brds/04-business-rules.md)).

### 6.2 Breadcrumb

Optional on admin deep pages. Items: home → section → current.

### 6.3 UserMenu

Header dropdown on all authenticated shells. Data sourced from auth context (`GET /auth/me`). Full spec: [10-user-flows.md](./10-user-flows.md) §14.

**Trigger**

- User icon + truncated `displayName` + chevron
- `data-testid="user-menu-trigger"`
- `aria-label`: `Tài khoản {displayName}`

**Dropdown panel (read-only identity header)**

- Primary: `displayName` (semibold)
- Secondary: `email` (truncate with `title` attribute for full value)
- Secondary: `institutionalId` prefixed with `Mã:`
- Role: localized `roleLabels[role]`
- Separator
- Logout item: `LogOut` icon + `appCopy.logout` ("Đăng xuất")
- `data-testid="user-menu-logout"`
- Disabled with `aria-busy` while logout in flight

**Props contract**

```ts
interface UserMenuProps {
  displayName: string;
  email: string;
  institutionalId: string;
  role: UserRole;
  onLogout: () => void | Promise<void>;
  isLoggingOut?: boolean;
}
```

`onLogout` is required at call sites — layouts must wire it from auth context; an unwired menu item is not acceptable for MVP.

---

## 7. Component API Conventions

| Convention | Rule |
| --- | --- |
| Naming | PascalCase; file matches export |
| Props | Extend native HTML props where applicable |
| `className` | Merge via `cn()` |
| `data-testid` | On interactive elements for E2E |
| Refs | Forward refs on inputs and buttons |
| i18n | No English default labels in component defaults |

---

## 8. Component Inventory Matrix

| Component | Primary FR | Used by roles |
| --- | --- | --- |
| `Button`, `Input`, `Form` | FR-02, FR-04 | All |
| `StatusBadge` | FR-05, FR-09 | Instructor, Student |
| `DataTable` | FR-03, FR-12 | Instructor, Admin |
| `PermissionGuideModal` | FR-07, FR-08 | Student |
| `CheckInOutcomePanel` | FR-09 | Student |
| `ConfirmDialog` | FR-11, FR-13 | Instructor, Admin |
| `Toast` | — | All |
| `StatCard` | FR-15 | Instructor |
| `RoleHomeHub`, `NavCard` | FR-18 | All authenticated |
| `RouteDiscoveryPanel` | FR-18 | Unauthenticated `/` |
| `UserMenu` | FR-02 | All authenticated |

---

## 9. Accessibility Requirements (All Components)

- Color contrast ≥ **4.5:1** for text ([NFR-20](../brds/07-non-functional-risk.md) where applicable).
- Focus visible on all interactive elements.
- Dialogs: `aria-labelledby`, initial focus on first focusable or title.
- Loading buttons: `aria-busy="true"`.
- Icons decorative: `aria-hidden="true"` when label present.

Full audit: [13-accessibility-basics.md](./13-accessibility-basics.md).

---

## 10. Future Consideration

- `Combobox` with async search for student lookup.
- `DatePicker` for session schedule (native `input type="datetime-local"` sufficient for MVP).
- `FileUpload` dropzone with CSV preview for roster import.
- Storybook stories for each `components/ui` export.
