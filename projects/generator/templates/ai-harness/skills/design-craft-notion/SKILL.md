---
name: design-craft-notion
description: Optional extension — workspace density patterns for admin/instructor shells (sidebar rhythm, listing toolbars, table spacing). Customize per product; tokens from docs/ui-ux win.
---

# Design Craft — Workspace Density (Extension Stub)

**Optional skill.** Customize this file per product when the app has workspace-style layouts (sidebar + data tables + listing toolbars). If your product does not use this pattern, agents may ignore this skill.

**Companion skill:** [`frontend-design`](../frontend-design/SKILL.md) — identity, signature moments, typography.

## Precedence (non-negotiable)

| Topic | Authoritative doc |
| --- | --- |
| Design spec (when present) | [docs/ui-ux/DESIGN.md](../../../docs/ui-ux/DESIGN.md) |
| Token values, colors, fonts | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) |
| Listing page matrix | [docs/ui-ux/14-listing-pages-search-filter-sort.md](../../../docs/ui-ux/14-listing-pages-search-filter-sort.md) (when present) |
| Table toolbar contract | [docs/ui-ux/05-common-ui-components.md](../../../docs/ui-ux/05-common-ui-components.md) |
| App shells / nav | [docs/ui-ux/06-app-layout-components.md](../../../docs/ui-ux/06-app-layout-components.md) |

Never import third-party reference hex values or fonts that conflict with product tokens.

---

## Patterns to apply (using product tokens)

| Pattern | Application |
| --- | --- |
| Calm canvas | Page background behind elevated cards — `--color-surface-default` |
| Elevated data card | Table + toolbar container — `--color-surface-elevated`, subtle shadow |
| Hairline dividers | Table rows, sidebar groups — `--color-border-subtle` |
| Compact sidebar rows | Admin/instructor nav — 36–40 px row height, consistent inset |
| Filter toolbar | Listing pages — search left, primary action right |
| Single active nav item | One active indicator per layout — per RBAC/nav spec |
| Muted metadata | Secondary table columns — muted text tokens |
| Empty list state | Icon + headline + one CTA |

---

## Sidebar chrome (when applicable)

1. **Width:** per `06-app-layout-components.md`
2. **Row rhythm:** 36–40 px touch height; consistent horizontal padding
3. **Groups:** subtle dividers between nav sections
4. **Active state:** exactly **one** active item per layout per permissions doc

---

## Listing toolbar (when applicable)

Every listing page per product matrix needs search + filter + sort + pagination (or documented variant).

**Desktop layout:**

```
┌─────────────────────────────────────────────────────────────┐
│ [Search………………]  [Filter ▾] [Sort ▾]     [Primary CTA]     │
├─────────────────────────────────────────────────────────────┤
│ Table header row                                            │
└─────────────────────────────────────────────────────────────┘
```

- Toolbar padding and control gaps per design tokens
- Mobile: stack search full-width; keep primary CTA reachable

---

## Table density

| Element | Guideline |
| --- | --- |
| Header row | Label style, muted color, bottom border |
| Body row height | min 44 px touch on user-facing tables |
| Cell padding | Comfortable inset per tokens |
| Pagination | Below table; per component spec |

---

## Customization

Replace this stub with product-specific examples during harness setup or in `skills/design-craft-notion/REFERENCE.md` if you need a longer pattern library. Wire paths in `config/context-map.json` under `agents.frontend.alwaysRead` and `agents.tester.alwaysRead`.
