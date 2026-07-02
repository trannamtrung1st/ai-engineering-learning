---
name: visual-design
description: Generic design-system craft for Attendly UI — read design-system modules, apply style profile tokens, and enforce screenshot review for implementer and browser tester agents.
---

# Visual Design Craft (Attendly Harness)

Harness skill for **Neobrutalism** visual implementation. Product specs live in `docs/ui-ux/`; this skill governs how agents read and apply them.

**Style profile:** borders (2px solid #000000), radius (0px), elevation (hard offset shadows with no blur (shadow-xs through shadow-2xl)), primary (#FFDB33), fonts (Archivo Black, sans-serif / Space Grotesk, sans-serif).

## Precedence (non-negotiable)

| Topic | Authoritative doc |
| --- | --- |
| Scope, module index, domain bridge | [docs/ui-ux/DESIGN.md](../../../docs/ui-ux/DESIGN.md) |
| Component visual specs | [docs/ui-ux/design-system/](../../../docs/ui-ux/design-system/) |
| CSS variable mapping | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) |
| Quality gate | [docs/ui-ux/00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) |
| Component contracts | [docs/ui-ux/05-common-ui-components.md](../../../docs/ui-ux/05-common-ui-components.md), [06-app-layout-components.md](../../../docs/ui-ux/06-app-layout-components.md) |
| Listing page matrix | [docs/ui-ux/14-listing-pages-search-filter-sort.md](../../../docs/ui-ux/14-listing-pages-search-filter-sort.md) |

Never bypass tokens, accessibility, or business rules for aesthetics.

---

## Before writing code

Read every module that applies to the screen:

| Screen type | Minimum modules |
| --- | --- |
| Any UI | `layout.md`, `typography.md`, `colors.md`, `shadows.md`, `radius.md`, `borders.md` |
| Forms / auth | + `inputs.md`, `buttons.md`, `cards.md` |
| Listing / data views | + `tables.md`, `tabs.md`, `sidebars.md` |
| Modals / dialogs | + `modals.md` |
| Outcome states | + `alerts.md`, `badges.md` |

Do NOT write UI code until relevant modules are loaded.

---

## Style signatures (required)

Apply the **Neobrutalism** profile consistently:

- **Borders:** per `borders.md` and DESIGN.md style profile (2px solid #000000)
- **Radius:** per `radius.md` (default 0px)
- **Elevation:** per `shadows.md` (hard offset shadows with no blur (shadow-xs through shadow-2xl))
- **Typography:** headings use Archivo Black, sans-serif; body uses Space Grotesk, sans-serif
- **Primary CTA:** uses primary token (#FFDB33) with documented contrast pair
- **Tokens:** agnostic names mapped in `tokens.css` — not literal framework defaults

---

## Anti-template bar

The UI must feel **intentional** — not a generic gray SaaS template. Craft failures:

- Default framework styling without token alignment
- Identical styling for success, warning, empty, and error states
- Raw hex in component CSS Modules
- Missing hover/focus/disabled states on interactive surfaces
- Listing routes without `TableToolbar` per docs

Every major flow needs one intentional visual moment: outcome alert, elevated stat card, or recovery affordance with clear hierarchy.

---

## Tester FAIL criteria

Flag as UX/visual defect when screenshots show:

- Token drift (wrong primary, radius, or elevation vs DESIGN.md)
- Missing borders/shadows where design-system modules require them
- Wrong fonts vs token mapping
- Touch targets below 44×44 px on primary mobile actions
- Outcome badges/alerts not matching DESIGN.md domain bridge

Cross-reference [ui-ux-testing](../ui-ux-testing/SKILL.md) and [ui-visual-verification.md](../../docs/ui-visual-verification.md).

---

## Ground it in the product

Read `docs/ui-ux/01-ui-ux-foundation.md` for personas, locales, and canonical states. Design for real users under real constraints — not a marketing landing page.
