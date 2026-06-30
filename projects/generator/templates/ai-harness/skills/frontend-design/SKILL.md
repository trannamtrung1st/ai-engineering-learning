---
name: frontend-design
description: Distinctive, intentional visual design for {{PRODUCT_NAME}} UI. Process and craft guidance for implementer and browser tester agents — aesthetic direction, typography, signature moments, and copy that avoid templated defaults.
source: https://github.com/anthropics/skills/tree/main/skills/frontend-design
license: See LICENSE.txt
---

# Frontend Design ({{PRODUCT_NAME}} Harness)

Adapted from the [Anthropic frontend-design skill](https://raw.githubusercontent.com/anthropics/skills/refs/heads/main/skills/frontend-design/SKILL.md). This skill governs **identity and signature craft**; workspace density patterns live in [`design-craft-notion`](../design-craft-notion/SKILL.md) when customized.

**Division of labor:**

| Skill | Owns |
| --- | --- |
| `frontend-design` (this file) | Product identity, typography personality, signature moments, copy tone, anti-template aesthetics |
| `design-craft-notion` | Sidebar density, database toolbars, table rhythm, listing layout (optional extension) |

## Precedence (non-negotiable)

When this skill conflicts with product specs, **product docs win**:

| Topic | Authoritative doc |
| --- | --- |
| Token values, colors, fonts | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) |
| Quality gate, touch targets | [docs/ui-ux/00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) |
| Copy, state labels | [docs/ui-ux/01-ui-ux-foundation.md](../../../docs/ui-ux/01-ui-ux-foundation.md) |
| Component contracts | [docs/ui-ux/05-common-ui-components.md](../../../docs/ui-ux/05-common-ui-components.md), [06-app-layout-components.md](../../../docs/ui-ux/06-app-layout-components.md) |

Never bypass tokens, accessibility, or business rules for aesthetics.

---

## Ground it in the product

Read `docs/ui-ux/01-ui-ux-foundation.md` and `docs/brds/01-stakeholders-scope.md` for personas, locales, and primary devices. Design for **real users under real constraints** — not a generic SaaS template.

**Audience:** Match viewport priorities from UI/UX docs (mobile-first vs desktop admin).

---

## Design thinking (before pixels)

1. **Purpose** — What job is this screen doing in the MVP workflow?
2. **Tone** — Pick a deliberate direction from design overview (calm professional, energetic consumer, dense admin, etc.)
3. **Differentiation** — One memorable moment per major flow (empty state, success, hero data visualization)
4. **Constraints** — Tokens, RBAC, validation states, loading honesty

---

## Visual craft rules

### Typography

- Use fonts from `04-design-tokens.md` — do not substitute system-ui defaults without doc approval
- Establish clear hierarchy: page title → section → label → metadata
- Avoid identical weight/size for headings and body

### Color and contrast

- Semantic colors for success/warning/danger — not one gray alert for every outcome
- Primary CTAs must meet contrast pairs in tokens
- Disabled states legible (≥ 3:1) but visibly inactive

### Layout and spacing

- Cards and tables need internal padding — content never flush to edges
- Stack related actions with consistent gap tokens
- Mobile: no horizontal scroll on 320px unless data table explicitly allows

### Anti-template checklist (FAIL if present)

- Interchangeable white cards with no product personality
- Default blue primary with no token alignment
- Lorem ipsum or demo copy in production routes
- Identical styling for success, warning, and error outcomes
- Flat gray admin tables with no hierarchy

---

## Implementer self-critique loop

Before `SLICE_DONE` on frontend slices:

1. Capture **320×568** and **1280×720** screenshots per modified route
2. Review against [ui-visual-verification.md](../../docs/ui-visual-verification.md)
3. Fix contrast, padding, and craft issues; re-screenshot
4. List paths in `ai-harness/state/progress.md`

---

## Browser tester craft FAIL criteria

Log `UX-*` (P1+) when screenshots show:

- Primary CTA unreadable or washed-out on mobile
- Touch targets below 44×44 px on primary actions
- Forbidden navigation visible to wrong role
- Generic/template UI where docs specify differentiated outcomes

See [ui-ux-testing](../ui-ux-testing/SKILL.md) for full taxonomy.

---

## Related

- [design-craft-notion](../design-craft-notion/SKILL.md) — optional workspace/listing extension
- [ui-visual-verification.md](../../docs/ui-visual-verification.md) — screenshot checklist
