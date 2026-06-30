# We Check — Accessibility Basics

Baseline accessibility requirements for **We Check** MVP. Targets **WCAG 2.1 Level AA** for student check-in and instructor session flows; admin tables meet AA for structure and keyboard use. Aligns with [NFR-17](../brds/07-non-functional-risk.md), [NFR-18](../brds/07-non-functional-risk.md), and [NFR-19](../brds/07-non-functional-risk.md).

**Related documents:** [UI states](./12-ui-states.md) · [User flows](./10-user-flows.md) · [Common UI components](./05-common-ui-components.md) · [Production quality bar](./00-production-ui-quality-bar.md) · [Forms and validation UX](./08-forms-validation-ux.md)

---

## 1. Accessibility Scope and Goals

| Goal | MVP requirement |
| --- | --- |
| Perceivable | Text alternatives for icons; color not sole status indicator |
| Operable | Full keyboard paths on desktop; **44 px** touch targets on mobile |
| Understandable | Vietnamese labels; consistent error patterns |
| Robust | Semantic HTML; ARIA only where native semantics insufficient |

**Priority surfaces:** `/check-in` (student), `/sessions/:id/qr-present` (projection legibility), `/admin/users` and roster tables.

**Out of scope MVP:** Formal third-party WCAG audit certificate; screen-reader testing on every admin edge case.

---

## 2. Accessibility — Language and Document Structure

| Requirement | Implementation |
| --- | --- |
| Page language | `<html lang="vi">` on all routes |
| Document title | `We Check — {page title}` per [09-page-list.md](./09-page-list.md) |
| Heading hierarchy | Single `h1` per page; no skipped levels (`h1` → `h2` → `h3`) |
| Landmarks | `header`, `nav`, `main`, `footer` via layout components ([06-app-layout-components.md](./06-app-layout-components.md)) |
| Skip link | **Bỏ qua đến nội dung chính** as first focusable element on desktop layouts |

---

## 3. Accessibility — Color and Contrast

Use design tokens from [04-design-tokens.md](./04-design-tokens.md).

| Element | Minimum contrast | Notes |
| --- | --- | --- |
| Body text on background | **4.5:1** | `--color-text-primary` on `--color-bg-base` |
| Large text (≥ **18 pt** bold or **24 pt**) | **3:1** | QR countdown on fullscreen |
| UI components and focus rings | **3:1** | Buttons, inputs, badges |
| `Button` variants | **4.5:1** label (≥ **3:1** disabled) | Token pairs in [04-design-tokens.md](./04-design-tokens.md) §3.2.1 — `primary`, `secondary`, `outline`, `ghost`, `danger` |
| `StatusBadge` | Text + icon or pattern | Never color-only ([AC-07](../brds/08-acceptance-mvp-future.md) success must show text *Có mặt*) |

**Harness verification:** The Ralph loop does not run axe-core. Implementer and browser tester agents verify button contrast and padding via **browser screenshots** against [ui-visual-verification.md](../../ai-harness/docs/ui-visual-verification.md) and this section.

**QR fullscreen:** White QR on `#000` background; countdown numerals **≥ 32 px** bold ([NFR-20](../brds/07-non-functional-risk.md)).

**Color-blind safety:** Attendance statuses use distinct Vietnamese labels and icons: Có mặt (✓), Vắng (—), Có phép (P), Chờ (?).

---

## 4. Accessibility — Keyboard and Focus

| Pattern | Behavior |
| --- | --- |
| Tab order | Logical DOM order; no positive `tabindex` |
| Focus visible | `--focus-ring` **2 px** offset on all interactive elements |
| Modals | Trap focus; **Esc** closes; restore focus to trigger |
| Dropdowns / `Select` | Arrow keys navigate; Enter selects; Radix defaults |
| Tables | Row actions reachable by Tab; Enter activates primary action |
| Fullscreen QR | **Esc** exits; focus moves to **Thoát** button on enter |

**Student mobile:** Primary flows are touch-first; keyboard path required for Bluetooth keyboard users on tablets.

---

## 5. Accessibility — Forms and Validation

Per [08-forms-validation-ux.md](./08-forms-validation-ux.md):

| Requirement | Implementation |
| --- | --- |
| Labels | Every input has visible `<label>` or `aria-label` |
| Required fields | `aria-required="true"` + visual asterisk with legend |
| Errors | `aria-invalid="true"`; `aria-describedby` links to error `id` |
| Error summary | On submit, focus first invalid field or form-level `Alert` |
| Autocomplete | `autocomplete="username"`, `current-password` on login |

**Login ([AC-02](../brds/08-acceptance-mvp-future.md)):** Announce form-level errors via `role="alert"` on `Alert` component.

---

## 6. Accessibility — Check-In Flow

**Traces:** [FR-07](../brds/03-functional-requirements.md), [FR-08](../brds/03-functional-requirements.md) · [AC-07](../brds/08-acceptance-mvp-future.md), [AC-08](../brds/08-acceptance-mvp-future.md)

| Step | Accessibility requirement |
| --- | --- |
| Camera permission | `PermissionGuideModal` readable steps; numbered list in `ol` |
| Scanner | `aria-label="Máy quét mã QR"` on viewfinder region; live region announces *Đã quét mã* |
| GPS capture | `aria-busy="true"` while `requesting` / `acquiring` / `submitting`; **`aria-busy="false"`** (or absent) when `ready` with *Vị trí đã sẵn sàng* — no spinner ([AC-08f](../brds/08-acceptance-mvp-future.md)) |
| GPS ready | Check icon + `role="status"` for static ready copy; submit button enabled without loading chrome |
| Outcome panel | `role="status"` on success; `role="alert"` on blocking errors |
| Retry actions | Button labels describe action: **Quét lại**, not generic **OK** |

**Motion:** Respect `prefers-reduced-motion` — disable QR countdown animation; show numeric seconds only.

**Camera-only users:** Scanner is visual; outcome and errors always textual. No information conveyed by camera feed alone.

---

## 7. Accessibility — Tables and Data Grids

Applies to `UserListTable`, `AttendanceRosterTable`, `SessionReportTable`, import preview.

| Requirement | Implementation |
| --- | --- |
| Table semantics | `<table>`, `<thead>`, `<tbody>`, `<th scope="col">` |
| Sortable columns | `aria-sort="ascending|descending|none"` on header ([AC-15b](../brds/08-acceptance-mvp-future.md)) |
| Row selection (future) | `aria-selected` on rows |
| Pagination | `nav aria-label="Phân trang"`; current page `aria-current="page"` |
| Toolbar | `search` role on search input; filters labeled |

**Dense admin tables:** Minimum row height **40 px** desktop; horizontal scroll container has `tabindex="0"` and `aria-label="Cuộn bảng ngang"`.

---

## 8. Accessibility — Dynamic Content and Live Regions

| Component | ARIA | Announcement |
| --- | --- | --- |
| `QrCountdown` | `aria-live="off"` visually; optional `aria-label="Còn {n} giây"` | Avoid spamming screen readers every second |
| `SessionMonitorDashboard` count | `aria-live="polite"` on stat change | *Đã điểm danh 98 trên 120* |
| Toast notifications | `role="status"` | Auto-dismiss **5 s**; pause on hover/focus |
| Import progress | `role="progressbar"` with `aria-valuenow` when determinate |
| Polling refresh | No full-page announcement; row-level updates only |

---

## 9. Accessibility — Icons and Images

| Asset | Requirement |
| --- | --- |
| Lucide icons (decorative) | `aria-hidden="true"` when adjacent text present |
| Icon-only buttons | Required `aria-label` in Vietnamese ([05-common-ui-components.md](./05-common-ui-components.md) §2.2) |
| QR code image | `alt=""` decorative when session title adjacent; fullscreen adds `aria-label="Mã QR điểm danh buổi học {name}"` |
| Empty state illustrations | `alt=""` if heading + body text convey meaning |
| Logo | `alt="We Check"` |

---

## 10. Accessibility — Dialogs and Confirmations

| Dialog | Requirements |
| --- | --- |
| `ConfirmDialog` | `role="alertdialog"`; focus first button or cancel per destructive pattern |
| `AttendanceEditDialog` | Labelled by `aria-labelledby` referencing student name |
| `PermissionGuideModal` | **Đóng** always reachable; focus trap |
| Session lifecycle confirms | Destructive actions (Hủy, Đóng) use `variant="danger"` + explicit consequence text |

Destructive default: focus **Hủy** (cancel), not confirm — prevents accidental keyboard submit.

---

## 11. Accessibility — Mobile and Touch

| Requirement | Value | Reference |
| --- | --- | --- |
| Minimum touch target | **44 × 44 px** | [NFR-17](../brds/07-non-functional-risk.md) |
| Spacing between targets | **8 px** minimum | Prevent mis-tap |
| Bottom nav | `nav aria-label="Điều hướng chính"` | Student layout |
| Pinch zoom | Not disabled on content pages | Required for low vision |
| Viewport | `maximum-scale` not set below **2** | Do not block zoom |

**iOS Safari / Android Chrome:** Test permission prompts with VoiceOver/TalkBack on physical devices before pilot.

---

## 12. Accessibility — Error Messages and Help

Align with [NFR-19](../brds/07-non-functional-risk.md):

| Principle | Example |
| --- | --- |
| Plain language | *Vui lòng bật GPS và cấp quyền định vị để điểm danh* ([AC-08c](../brds/08-acceptance-mvp-future.md)) |
| Actionable | Every error includes next step or link to `PermissionGuideModal` |
| Persistent critical errors | `role="alert"` until dismissed or resolved |
| Permission help | Step-by-step with platform screenshots in modal |

Forbidden and export denial messages readable by assistive tech ([AC-12b](../brds/08-acceptance-mvp-future.md), [AC-13b](../brds/08-acceptance-mvp-future.md)).

---

## 13. Accessibility — Testing Checklist (MVP)

| Check | Tool / method | Pass criteria |
| --- | --- | --- |
| Automated scan | axe-core in CI on key routes | Zero critical violations |
| Keyboard walkthrough | Manual | Login, create session, open QR, export CSV completable |
| Screen reader smoke | VoiceOver (iOS), NVDA (Windows) | Check-in success path announced |
| Zoom **200%** | Browser | No clipped content on `/check-in` |
| Contrast | Token audit | All text pairs meet §3 ratios |
| Focus order | Tab through modals | Trap and restore verified |

---

## 14. Component Accessibility Contracts

Primitives from [05-common-ui-components.md](./05-common-ui-components.md) must ship with:

| Component | Contract |
| --- | --- |
| `Button` | `disabled` and `loading` set `aria-disabled`; loading adds `aria-busy` |
| `StatusBadge` | Visible text always present |
| `Alert` | `role="alert"` for danger; `role="status"` for info/success |
| `Tabs` | Radix `Tabs` with `aria-selected` on triggers |
| `Skeleton` | `aria-hidden="true"`; parent region `aria-busy="true"` |
| `EmptyState` | Heading level appropriate; CTA is real `button` or `a` |

---

## 15. Future Consideration

- Full WCAG 2.2 audit with remediation backlog.
- High-contrast theme toggle for projection environments.
- `aria-keyshortcuts` for instructor power users (e.g., **O** open session).
- Automated pa11y on all **17** MVP pages.
- Vietnamese screen-reader pronunciation guide for student IDs and class codes.
