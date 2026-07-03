# Attendly — Accessibility Basics

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Authoritative visual spec:** [DESIGN.md](./DESIGN.md)  
**Related docs:** [03-design-system-basics.md](./03-design-system-basics.md) · [04-design-tokens.md](./04-design-tokens.md) · [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md) · [08-forms-validation-ux.md](./08-forms-validation-ux.md) · [12-ui-states.md](./12-ui-states.md) · [../brds/07-non-functional-risk.md](../brds/07-non-functional-risk.md)

## 1. Purpose and scope

This document defines the **accessibility baseline** for Attendly MVP. Requirements apply to all surfaces (SUR-01 through SUR-05) and support keyboard, screen-reader, touch, and visual users during time-critical classroom operations. Attendly targets WCAG 2.1 Level AA intent for MVP; formal third-party audit is a post-launch activity.

### 1.1 Accessibility principles

| ID | Principle | Rationale |
| --- | --- | --- |
| `NFR-A11Y-01` | Perceivable — information is available through multiple senses | Status cannot rely on color alone (`NFR-UI-09`) |
| `NFR-A11Y-02` | Operable — all staff workflows work by keyboard | Admin and lecturer dense tables (`NFR-UI-08`) |
| `NFR-A11Y-03` | Understandable — errors state problem and fix | Check-in failures need recovery text (`FR-UI-03`) |
| `NFR-A11Y-04` | Robust — semantic HTML and ARIA where needed | Screen-reader compatibility for roster and audit |

---

## 2. Global accessibility requirements

### 2.1 Focus management

| Requirement | Specification | Trace |
| --- | --- | --- |
| Visible focus ring | All interactive controls show `:focus-visible` ring using token from [04-design-tokens.md](./04-design-tokens.md); minimum 2px contrast against background | `NFR-UI-08`, `NFR-DS-01` |
| Logical tab order | Tab sequence follows visual reading order in shells and modals | `NFR-LAY-05` |
| Focus trap in modals | `ConfirmActionModal`, `ManualCorrectionDialog` trap focus while open; restore focus to trigger on close | `NFR-LAY-06` |
| Skip link | Staff layouts (`LAY-02`–`LAY-04`) include "Skip to main content" as first focusable element | `NFR-A11Y-02` |
| Post-submit focus | Form validation failure moves focus to first invalid field | [08-forms-validation-ux.md](./08-forms-validation-ux.md) §6 |

### 2.2 Color and contrast

| Element | Rule |
| --- | --- |
| Body text | Minimum 4.5:1 contrast against background |
| Large headings / QR labels | Minimum 3:1 |
| `StatusBadge` | Icon or text label accompanies color coding — never color-only status |
| Neobrutalism borders | Black borders provide non-color structure for shape-boundary users |
| Error/success states | Icon + text message required (`NFR-UI-09`) |

Semantic palettes: [DESIGN.md](./DESIGN.md) §4.3, [colors.md](./design-system/colors.md).

### 2.3 Touch and pointer targets

| Surface | Minimum target | Spacing |
| --- | --- | --- |
| Student check-in (SUR-01) | 44×44 CSS px for primary CTA and retry actions | 8px minimum between adjacent targets |
| Lecturer session controls | 40×40 CSS px for open/close actions | Adequate padding in `SessionControlBar` |
| Table row actions | 36×36 CSS px minimum with expanded hit area | `NFR-UI-11` |

### 2.4 Motion and animation

| Rule | Detail |
| --- | --- |
| Respect `prefers-reduced-motion` | Disable QR crossfade and countdown ring animation; show numeric seconds only |
| No auto-playing distraction | Live roster updates use brief highlight, not continuous motion |
| Countdown | `QrCountdownRing` always exposes numeric `aria-live` seconds label |

---

## 3. Semantic structure and landmarks

### 3.1 Page landmarks

| Layout | Required landmarks |
| --- | --- |
| `LAY-01` (student) | `header` (minimal), `main` |
| `LAY-02`–`LAY-04` (staff) | `nav` (sidebar), `header` (`TopContextHeader`), `main`, optional `aside` for split panels |

### 3.2 Heading hierarchy

- One `h1` per route matching page title (e.g. "Buổi học hôm nay", "Điểm danh").
- Section headings (`h2`/`h3`) for toolbars, tables, and form groups.
- Status badges are not headings — use `span` with appropriate role.

### 3.3 Live regions

| Context | ARIA pattern | Announcement |
| --- | --- | --- |
| Check-in result | `role="status"` `aria-live="polite"` | Final outcome text on `CheckInResultScreen` |
| Form errors | `role="alert"` `aria-live="assertive"` | First error summary on submit failure |
| Live roster update | `aria-live="polite"` on count summary | "28 có mặt, 2 trễ, 15 chờ" on significant change |
| QR countdown | `aria-live="off"` with periodic polite update every 10 s | Seconds remaining (not every second) |
| Export success | `role="status"` | "Xuất CSV thành công" |

---

## 4. Surface-specific accessibility

### 4.1 Student check-in (SUR-01)

| Component | Accessibility requirement |
| --- | --- |
| `CheckInResultScreen` | Outcome announced via live region; success icon has `aria-hidden` with text equivalent |
| `GpsPermissionPrompt` | Explain purpose before system permission; buttons have descriptive labels ("Cho phép truy cập vị trí") |
| Login form (FRM-01) | Fields labeled; errors associated via `aria-describedby` |
| Retry after `ExpiredQr` | Primary button is first focusable element on failure screen |

Student copy is Vietnamese (`vi-VN`); `lang="vi"` on document root.

### 4.2 Lecturer session control (SUR-02)

| Component | Accessibility requirement |
| --- | --- |
| `QrDisplayPanel` | QR image has `alt` describing session; manual refresh button labeled "Làm mới mã QR" |
| `QrCountdownRing` | `role="timer"` or text label "Còn 24 giây"; ring is decorative (`aria-hidden`) when numeric label present |
| `SessionControlBar` | Open/close buttons name session context: "Mở điểm danh CS101-A Buổi 15" |
| Session `StatusBadge` | Text content matches state name; not icon-only |

Projection legibility (`AC-UI-06`) complements accessibility: high contrast QR benefits low-vision users in classroom.

### 4.3 Live roster (SUR-03)

| Pattern | Requirement |
| --- | --- |
| `DataTable` | `<table>` with `<th scope="col">`; row actions in dedicated column |
| Sort | Sortable headers are `<button>` with `aria-sort` state |
| Row correction | Action button includes student name: "Sửa điểm danh Nguyễn A" |
| Rejected attempt tooltip | Tooltip content available to keyboard via focus; not hover-only |
| Virtualized list | `aria-rowcount` / `aria-rowindex` when virtualization used |

Realtime updates must not steal focus from active correction dialog (`NFR-UI-06`).

### 4.4 Admin listings and forms (SUR-04)

| Pattern | Requirement |
| --- | --- |
| `TableToolbar` | Search input has `aria-label`; filter chips removable via keyboard |
| Pagination | Current page announced; prev/next buttons labeled |
| File upload (FRM-06) | Native file input accessible; drop zone has keyboard activation |
| Policy form (FRM-07) | Toggle switches use `role="switch"` `aria-checked` |
| `PolicyResolutionSummary` | Accordion headers are `<button aria-expanded>` |

### 4.5 Reporting and audit (SUR-05)

| Pattern | Requirement |
| --- | --- |
| Date range filters | Inputs labeled "Từ ngày" / "Đến ngày"; error if range invalid |
| `ExportScopeSummary` | Scope read aloud before confirm; destructive/export confirm in modal |
| `AuditEntryRow` | Expandable detail via accordion; change summary text readable without opening |
| Permission denied | Alert role; no partial data in DOM for unauthorized scope |

---

## 5. Keyboard interaction patterns

### 5.1 Global shortcuts (staff)

| Key | Context | Action |
| --- | --- | --- |
| `Tab` / `Shift+Tab` | All | Move focus forward/backward |
| `Enter` / `Space` | Buttons, chips | Activate |
| `Escape` | Modals, dropdowns | Close and restore focus |
| `Arrow keys` | Dropdown menus, sort menus | Navigate options |

No custom shortcut conflicts with browser or assistive technology defaults.

### 5.2 TableToolbar keyboard flow

1. Tab to search field → type query → `Enter` applies.
2. Tab to filter dropdown → `Enter` opens → arrows select → `Enter` confirms.
3. Active filter chips: `Delete` or chip button removes filter.
4. Tab to sort control → same dropdown pattern.

Reference: [05-common-ui-components.md](./05-common-ui-components.md) §4, [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md).

### 5.3 Modal keyboard flow

1. Open modal → focus moves to first focusable control (usually primary action or first field).
2. `Tab` cycles within modal only.
3. `Escape` or Cancel → close and return focus to trigger element.

Applies to: `ConfirmActionModal`, `ManualCorrectionDialog`, export confirm (PG-14).

---

## 6. Forms and validation accessibility

| Requirement | Implementation |
| --- | --- |
| Explicit labels | Every input has visible `<label>` or `aria-label`; placeholders are supplementary only (`NFR-UI-10`) |
| Required fields | `aria-required="true"` and visual required indicator (not color alone) |
| Error association | `aria-invalid="true"` + `aria-describedby` pointing to error message id |
| Error announcement | Summary `role="alert"` on submit; field errors announced on blur |
| Reason field (manual correction) | Textarea labeled "Lý do" with helper text when policy mandates |

Full form specs: [08-forms-validation-ux.md](./08-forms-validation-ux.md) §6.

---

## 7. Testing and verification checklist

### 7.1 Manual test checklist

| ID | Check | Pass condition |
| --- | --- | --- |
| `CHK-A11Y-01` | Keyboard-only staff flow | Lecturer can open session, view roster, apply correction without mouse |
| `CHK-A11Y-02` | Screen reader check-in | Student hears success/failure outcome on `CheckInResultScreen` |
| `CHK-A11Y-03` | Focus visibility | Every interactive element shows focus ring on keyboard navigation |
| `CHK-A11Y-04` | Color independence | Status understood with grayscale simulation |
| `CHK-A11Y-05` | Touch targets | Student CTAs meet 44px minimum on 375px viewport |
| `CHK-A11Y-06` | Reduced motion | QR rotation respects `prefers-reduced-motion` |
| `CHK-A11Y-07` | Modal focus trap | Focus does not escape open modals |
| `CHK-A11Y-08` | Table semantics | Roster and report tables expose correct header/row structure |

### 7.2 Automated tooling (CI recommendation)

- axe-core or eslint-plugin-jsx-a11y on component tests.
- Lighthouse accessibility audit on PG-01, PG-02, PG-05, PG-06, PG-13 in CI smoke pipeline.
- Color contrast verification against [04-design-tokens.md](./04-design-tokens.md) semantic pairs.

---

## 8. Traceability

| Accessibility concern | Requirement links |
| --- | --- |
| Focus and keyboard | `NFR-UI-08`, `NFR-DS-03`, `NFR-LAY-04`–`NFR-LAY-06` |
| Contrast and non-color status | `NFR-UI-09`, `NFR-DS-02` |
| Mobile touch | `NFR-UI-11`, `NFR-14` |
| Form labels and errors | `NFR-UI-10`, `NFR-VAL-01`, `NFR-VAL-02` |
| Check-in clarity | `AC-UI-01`–`AC-UI-03`, `FR-UI-03` |
| Listing operability | `AC-UI-07`, `FR-TTB-01`–`FR-TTB-05` |

---

## 9. Future consideration

- Formal WCAG 2.2 audit with remediation backlog.
- Screen-reader-optimized "compact roster" mode for lecturers.
- High-contrast theme variant beyond default Neobrutalism palette.
- Institution-specific accessibility compliance packs (Section 508, EN 301 549).
