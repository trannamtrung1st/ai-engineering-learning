# Sidebars

> Dependencies: `colors.md`, `radius.md`, `typography.md`, `badges.md`, `alerts.md`

## Core Specs

- Background: neutral-primary-soft
- Right border: 2px solid border-default (for left-sidebar); left border for right-sidebar
- Width: 256px

## Anatomy

### Outer Container
Hidden on mobile, visible at small breakpoint. Needs a toggle/trigger for mobile.

### Inner Wrapper
- Full height, vertical scroll overflow
- Padding: 12px horizontal, 16px vertical

### Navigation List
- First item **must** be the role's home/dashboard link:
  - Lecturer / DepartmentAdmin: "Phiên học" → `/lecturer/sessions`
  - AcademicAdmin: "Thiết lập học kỳ" → `/admin/terms`
  - ITAdmin / SystemAuditor: "Nhật ký kiểm toán" → `/audit/logs`
  - Student (via StudentLayout, not sidebar): "Trang chủ" link → `/check-in`
- Vertical spacing: 8px between items
- Font weight: semibold

### Navigation Item
- Layout: flex, vertically centered
- Padding: 8px horizontal, 8px vertical
- Text: heading color
- Radius: 0px (base)
- Hover: neutral-secondary-medium background
- Transition: colors
- Icon: 20x20px, body color, hover → heading color, 75ms transition
- Label: 12px left margin from icon

### Active Item
- Background: neutral-secondary-strong
- Text: fg-brand-strong

### Separator
- 16px top padding, 16px top margin
- Top border: 2px solid border-default
- 8px vertical spacing below

### Bottom CTA / Card
- Padding: 16px
- Top margin: 24px
- Radius: 0px (base)
- Background: brand-softer
- Border: 2px solid border-brand-subtle
- Can also use any alert variant from `alerts.md`

### Logout control
- Label: **Đăng xuất**
- Placement: below the navigation list, separated by a `Separator` (staff `SidebarNav`); student mobile shell uses header or account menu per `LAY-01`
- Style: text button or low-emphasis secondary button — not primary brand CTA
- Action: FLOW-15 (`FR-38`) — `POST /v1/auth/logout`, clear client credentials, redirect to `/login`
- Always visible on authenticated pages for the active role

## Rules

- **Home link first:** the top nav item is always the role's primary dashboard link (see Navigation List above) — never omit it, never move it below the fold, never make it conditional.
- **RBAC gating:** render only the nav items that the current user's role is permitted to access, as determined by `role-guard.ts` functions and `docs/technical/01-roles-permissions.md`. Do **not** render forbidden items as disabled anchor tags — omit them from the DOM entirely. CSS `display:none` or `pointer-events:none` on forbidden items is also forbidden; the item must not be present in the rendered output.
- **No dead ends:** every item in the nav list must link to a real, implemented route. Never add a nav item as a placeholder.
- Responsive: hidden on mobile with a trigger mechanism
- Icons: 20x20px, body color (hover: heading color)
- Multi-level menus: indent with 44px left padding
- Spacing follows 8px grid
- Only neutral, brand, or status tokens — no arbitrary colors
