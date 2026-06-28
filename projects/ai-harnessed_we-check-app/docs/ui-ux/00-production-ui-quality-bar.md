# We Check — Production UI Quality Bar

Minimum visual, interaction, and accessibility standards for **We Check** MVP. Every frontend slice must meet this bar before merge. Derived from [BRD prompt](../brds/prompt.md), [NFR-17](../brds/07-non-functional-risk.md)–[NFR-20](../brds/07-non-functional-risk.md), and [12-backend-frontend-tech-stack.md](../technical/12-backend-frontend-tech-stack.md).

**Related documents:** [UI/UX foundation](./01-ui-ux-foundation.md) · [Design tokens](./04-design-tokens.md) · [Common components](./05-common-ui-components.md) · [App layout components](./06-app-layout-components.md)

---

## 1. Purpose

Define what “production-ready” means for We Check UI so engineers, designers, and reviewers apply a consistent quality gate. This document is the checklist referenced by implementer and reviewer agents.

---

## 2. Quality Dimensions

| Dimension | MVP target | Verification |
| --- | --- | --- |
| Visual consistency | All screens use design tokens from [04-design-tokens.md](./04-design-tokens.md); no ad-hoc hex values in components | Design review; lint for hard-coded colors |
| Localization | **100%** user-facing copy in Vietnamese (`vi-VN`) per [NFR-17](../brds/07-non-functional-risk.md) | Copy audit against `@wecheck/domain` message keys |
| Mobile check-in | Student flows usable on **320 px** width; touch targets ≥ **44×44 px** | Device matrix: iOS 15+ Safari, Android 10+ Chrome |
| Projector QR display | QR scannable at **5 m** on **1280×720** projection; countdown ≥ **4.5:1** contrast per [NFR-20](../brds/07-non-functional-risk.md) | Classroom field test |
| Accessibility baseline | WCAG 2.1 AA for color contrast, focus visibility, form labels, and dialog focus trap | axe-core or equivalent on critical paths |
| Performance perception | Check-in screen interactive within **2 s** on 4G; no layout shift during QR countdown | Lighthouse mobile on `/check-in` |
| Error clarity | Every API `errorCode` maps to a Vietnamese user message with recovery action per [NFR-19](../brds/07-non-functional-risk.md) | Walkthrough with denied camera/GPS |
| State honesty | Loading, empty, error, and success states explicit; no silent failure | [12-ui-states.md](./12-ui-states.md) coverage (downstream) |

---

## 3. Acceptable

The following are **acceptable** for MVP release:

- Utility-first Tailwind styling with Radix primitives as specified in [02-ui-framework-tech-stack.md](./02-ui-framework-tech-stack.md).
- Polling-based live attendance refresh every **5 seconds** instead of WebSockets ([FR-15](../brds/03-functional-requirements.md)).
- System font stack (no custom web font) to reduce load on student check-in pages.
- Instructor and admin layouts optimized for **1024 px+** desktop; student layout mobile-first only.
- Toast notifications for transient success/error; inline alerts for blocking form errors.
- Skeleton loaders on data tables and session lists while TanStack Query fetches.
- Permission-denied modals with platform-specific Vietnamese instructions (Safari vs Chrome).
- High-contrast QR display mode (dark background, white QR modules) for projector use.
- Manual attendance fallback link visible on student check-in error screens ([FR-11](../brds/03-functional-requirements.md)).
- Audit-sensitive actions (manual edit, CSV export) require explicit confirmation dialog.

---

## 4. Not Acceptable

The following are **not acceptable** and block merge:

- English user-facing strings on production paths (technical IDs and developer logs excepted).
- Check-in flow requiring native app install or unsupported browser APIs without fallback.
- GPS or camera access without prior consent copy explaining purpose and data handling ([NFR-12](../brds/07-non-functional-risk.md)).
- Raw API error text or stack traces shown to users.
- Buttons or links smaller than **44×44 px** on student touch surfaces.
- QR display with countdown timer below **4.5:1** contrast against background.
- Optimistic UI that marks check-in successful before server confirms ([12-backend-frontend-tech-stack.md](../technical/12-backend-frontend-tech-stack.md) §4.5).
- Custom modal implementations that break keyboard focus trap or Escape dismissal.
- Hard-coded colors bypassing CSS variables in [04-design-tokens.md](./04-design-tokens.md).
- Admin-only actions (CSV export per [BR-09](../brds/04-business-rules.md)) visible without role guard in UI.
- Stub copy, filler text, or unfinished strings in any shipped route.
- Layout that hides critical session state (e.g., `Active` vs `Closed`) from instructor during live session.

---

## 5. Role-Specific Bars

### 5.1 Student (`Student`)

| Requirement | Bar |
| --- | --- |
| Check-in path | ≤ **3 taps** from login to scan attempt ([AC-07](../brds/08-acceptance-mvp-future.md)) |
| Outcomes | All check-in outcomes (`Success`, `ExpiredQr`, `OutOfRadius`, etc.) have distinct UI treatment |
| Offline | Network retry up to **3** attempts within **30 s** with visible progress |

### 5.2 Instructor (`Instructor`)

| Requirement | Bar |
| --- | --- |
| Session open | Block activation UI when room GPS missing ([BR-07](../brds/04-business-rules.md)) |
| QR view | Full-screen mode; auto-refresh countdown; no chrome obscuring QR |
| Live monitor | Present / Pending / Absent counts update within polling interval |

### 5.3 Training Office Admin (`TrainingOfficeAdmin`)

| Requirement | Bar |
| --- | --- |
| Data tables | Server pagination; sortable columns; empty state with import CTA |
| Export | CSV export shows progress and download confirmation |

---

## 6. Review Checklist

Before marking a UI slice complete, confirm:

1. Meets all **Not acceptable** negations above.
2. Traces to at least one `FR-xx` or `AC-xx` in PR description.
3. Uses components from [05-common-ui-components.md](./05-common-ui-components.md) and layouts from [06-app-layout-components.md](./06-app-layout-components.md).
4. Vietnamese copy reviewed by second reader or checklist.
5. Tested on one iOS Safari and one Android Chrome device for student paths.

---

## 7. Future Consideration

- Automated visual regression (Chromatic or Percy) on layout shells.
- Dark mode token set for instructor night sessions.
- Reduced-motion variants for countdown animations.
- Formal WCAG audit report for institutional compliance sign-off.
