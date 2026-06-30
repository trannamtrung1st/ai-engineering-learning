---
name: design-craft-notion
description: Notion workspace density for We Check instructor/admin shells — sidebar rhythm, database toolbars, table spacing, empty states. Implements DESIGN.md workspace patterns.
source: https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/notion/DESIGN.md
---

# Design Craft — Notion Patterns (We Check Harness)

Implements workspace layout density from [docs/ui-ux/DESIGN.md](../../../docs/ui-ux/DESIGN.md) (vendored Notion spec). CSS values live in [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md).

**Companion skill:** [`frontend-design`](../frontend-design/SKILL.md) — identity, signature moments, typography, screenshot craft.

## Precedence (non-negotiable)

| Topic | Authoritative doc |
| --- | --- |
| Design spec | [docs/ui-ux/DESIGN.md](../../../docs/ui-ux/DESIGN.md) |
| Token values, colors, fonts | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) §5 |
| Listing page matrix | [docs/ui-ux/14-listing-pages-search-filter-sort.md](../../../docs/ui-ux/14-listing-pages-search-filter-sort.md) §0 |
| Table toolbar contract | [docs/ui-ux/05-common-ui-components.md](../../../docs/ui-ux/05-common-ui-components.md) §4.2 |
| Sidebar / nav matching | [docs/ui-ux/06-app-layout-components.md](../../../docs/ui-ux/06-app-layout-components.md) §6.2a |
| Signature moments / outcome panels | [frontend-design SKILL](../frontend-design/SKILL.md) |

**Out of scope for app routes:** pricing tiers, FAQ accordions, logo walls, sticky-note hero decorations, pastel marketing feature bands — see DESIGN.md preamble.

---

## Workspace patterns (DESIGN.md components)

| DESIGN.md component | We Check application | CSS tokens |
| --- | --- | --- |
| `colors.surface` canvas | Page background behind cards | `--color-surface-default` |
| `card-base` | Table + toolbar container | `--color-surface-raised` + `--shadow-sm` + hairline border |
| `colors.hairline` | Table rows, sidebar groups | `--color-border-default` |
| Sidebar rows | Instructor/admin nav | 36–40 px row height, `--space-3` inset |
| `search-pill` | Listing page search | `TableToolbar` per [05-common-ui-components](../../../docs/ui-ux/05-common-ui-components.md) §4.2 |
| `pill-tab-active` | Singleton nav indicator | `--color-primary-50` bg, `--color-primary-600` text |
| `colors.steel` | Table secondary columns | `--color-text-muted`, `text-small` |
| Empty database | Zero-row listings | Icon + headline + one CTA (Vietnamese) |
| `hero-band-dark` | Auth desktop left panel | `--color-brand-700` navy |
| `button-primary` | Login + primary CTAs | `--color-primary-600` purple |

---

## Sidebar workspace chrome

Applies to `InstructorLayout` and `AdminLayout`:

1. **Width:** 240–260 px desktop; collapsible below `lg` per layout spec
2. **Row rhythm:** 36–40 px touch height; `--space-3` horizontal padding; icon + label gap `--space-2`
3. **Groups:** hairline `--color-border-default` between nav sections (main vs settings)
4. **Active state:** exactly **one** pill per layout — see §6.2a route table; never two siblings active ([BR-14a](../../../docs/brds/04-business-rules.md))
5. **No brand stripe** — calm Notion sidebar without leading-edge accent bar

Student `BottomNav` uses pill active indicator with same singleton rule at mobile scale.

---

## Database toolbar (listing pages)

Every page in [14-listing-pages §0](../../../docs/ui-ux/14-listing-pages-search-filter-sort.md) needs search + filter + sort + pagination (or documented variant).

**Toolbar layout (desktop):**

```
┌─────────────────────────────────────────────────────────────┐
│ [🔍 Search………………]  [Filter ▾] [Sort ▾]     [Primary CTA] │
├─────────────────────────────────────────────────────────────┤
│ Table header row                                            │
│ …                                                           │
└─────────────────────────────────────────────────────────────┘
```

**Rules:**

- Search uses `search-pill` styling (`--color-surface-default` bg, hairline border, 44 px height)
- Search left; primary action right (e.g. **Thêm lớp**, **Xuất CSV** on report pages per [BR-09](../../../docs/brds/04-business-rules.md))
- Toolbar padding `--space-4`; control gap `--space-3`
- Mobile: stack search full-width above filter row; keep CTA reachable
- Report pages: `ReportFilterBar` satisfies filter; inline **Xuất CSV** in toolbar for permitted roles

---

## Table density

| Element | Spec |
| --- | --- |
| Header row | `text-label`, `--color-text-muted`, bottom border `--color-border-default` |
| Body row height | min 44 px (touch) on student-facing; 40–44 px admin |
| Cell padding | `--space-3` vertical, `--space-4` horizontal |
| Hover | `--color-surface-muted` on row hover only — no heavy striping |
| Status badges | `badge-tag-*` pastel pattern per [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) §12 |
| Pagination | Below table, right-aligned; “Trang X / Y” per component spec |

Roster tables ≤150 rows may omit paging UI per §0 matrix — still show search/filter.

---

## Empty and loading states

Notion-style empty databases:

- Centered in card area; Lucide icon 32 px muted
- `text-h2` headline Vietnamese — state-specific (“Chưa có buổi học nào”)
- One primary CTA linking to create flow
- No lorem ipsum; no decorative illustration clutter

Loading: skeleton rows matching table column count — not a single spinner covering the whole page.

---

## Slice-specific guidance

| Slice area | Focus |
| --- | --- |
| `web-visual-refresh-v2` | Shell surfaces + sidebar density foundation |
| `web-design-system-shell` | `TableToolbar`, `DataTable`, layout primitives |
| `web-role-navigation` | Singleton active nav; sidebar group spacing |
| `web-admin-*` listing | Full §0 toolbar matrix |
| `web-instructor-reports` | `ReportFilterBar` + inline CSV for assigned scope |
| `web-instructor-session-monitor` | Monitor roster filter row |

Student check-in routes: **minimal chrome** — apply [`frontend-design`](../frontend-design/SKILL.md) signature moments, not database toolbars.

---

## Implementer checklist

1. Read [DESIGN.md](../../../docs/ui-ux/DESIGN.md) preamble and [14-listing-pages §0](../../../docs/ui-ux/14-listing-pages-search-filter-sort.md) when slice touches a collection view
2. Implement `TableToolbar` before table body on admin/instructor listings
3. Verify sidebar shows exactly one active item on nested routes (especially `/admin/rosters/import` vs `/admin/rosters`)
4. Use tokens from [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) only
5. Dual-viewport screenshots for modified listing pages (320 + 1280)

---

## Browser tester checklist

**FAIL** when:

- Listing page missing search, filter, sort, or pagination per §0
- Two sidebar items show active styling simultaneously
- Toolbar controls cramped (< `--space-3` gap) or primary CTA buried below fold on desktop
- Table rows lack hairline separation; unreadable muted metadata
- Empty state is generic “No data” in English with no action

**PASS** when:

- Notion workspace density present with DESIGN.md tokens applied
- Singleton active nav verified on screenshot evidence
- Report pages show **Xuất CSV** only for permitted roles

Cite screenshot path as evidence. Cross-check [`frontend-design`](../frontend-design/SKILL.md) for non-template craft on the same captures.

---

## Reference

Trimmed upstream spacing/elevation notes: [REFERENCE.md](./REFERENCE.md)
