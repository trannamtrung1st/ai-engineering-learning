# We Check — UI Framework and Tech Stack

Frontend framework choices and UI layer architecture for **We Check**. Aligns with [12-backend-frontend-tech-stack.md](../technical/12-backend-frontend-tech-stack.md) and maps stack decisions to implementable UI structure.

**Related documents:** [Design system basics](./03-design-system-basics.md) · [Design tokens](./04-design-tokens.md) · [Common components](./05-common-ui-components.md) · [App layout components](./06-app-layout-components.md)

---

## 1. Framework

We Check ships as a **Vite** single-page application using **React 18** and **TypeScript** strict mode. UI is utility-styled with **Tailwind CSS 3.x** and accessible primitives from **Radix UI**. This document specifies how those technologies compose the presentation layer in `apps/web`.

---

## 2. Stack Summary

| Layer | Technology | Version | UI role |
| --- | --- | --- | --- |
| Build | Vite | 5+ | Fast HMR; code-split routes |
| UI library | React | 18+ | Component model |
| Language | TypeScript | 5.x | Props typing; shared domain types |
| Styling | Tailwind CSS | 3.x | Layout, spacing, responsive breakpoints |
| Primitives | Radix UI | Latest stable | Dialog, dropdown, toast, tabs, tooltip |
| Icons | Lucide React | Latest stable | Stroke icons, **24 px** default |
| Routing | React Router | v6 | Role-based route trees |
| Server state | TanStack Query | v5 | API cache, polling, mutations |
| Forms | React Hook Form + Zod | — | Shared schemas from `@wecheck/domain` |
| Tables | TanStack Table | v8 | Admin lists, attendance rosters |
| Toasts | Sonner or Radix Toast | — | Vietnamese feedback messages |
| QR (display) | `qrcode` | — | PNG/SVG for instructor view |
| QR (scan) | `BarcodeDetector` / `@zxing/browser` | — | Student camera scan |

---

## 3. Monorepo Package Boundaries

```
apps/web/
  src/
    app/           # Router, providers, role shells
    components/    # Shared UI (see 05-common-ui-components.md)
    features/      # Domain screens (sessions, check-in, admin)
    hooks/         # useAuth, usePolling, useGeolocation
    lib/           # api-client, cn(), formatters
    styles/        # globals.css, token imports
packages/domain/   # @wecheck/domain — enums, Zod, Vietnamese messages
```

**Rule:** No business rule duplication in UI — validate with shared Zod schemas; attendance outcomes come from API only.

---

## 4. Application Bootstrap

### 4.1 Provider tree

```tsx
<QueryClientProvider>
  <AuthProvider>
    <ToastProvider>
      <RouterProvider router={appRouter} />
    </ToastProvider>
  </AuthProvider>
</QueryClientProvider>
```

### 4.2 Query client defaults

| Option | Value | Rationale |
| --- | --- | --- |
| `staleTime` | 30 s (lists), 0 (check-in) | Balance freshness vs load |
| `retry` | 3 for check-in mutation | Network flake during peak |
| `refetchOnWindowFocus` | true for instructor | Return-to-tab refresh |

### 4.3 API client

- Base path: `/api/v1` (proxied in dev per [10-local-development-setup.md](../technical/10-local-development-setup.md)).
- Credentials: `include` for session cookie `wecheck_session`.
- Bearer fallback header for mobile fetch edge cases ([12-backend-frontend-tech-stack.md](../technical/12-backend-frontend-tech-stack.md) §3.4).
- Map `errorCode` to `@wecheck/domain` Vietnamese strings.

---

## 5. Routing Architecture

### 5.1 Route groups by role

| Prefix | Role guard | Layout |
| --- | --- | --- |
| `/login` | Public | `AuthLayout` |
| `/check-in`, `/history` | `Student` | `StudentLayout` |
| `/sessions/*` | `Instructor` | `InstructorLayout` |
| `/admin/*` | `TrainingOfficeAdmin` | `AdminLayout` |

Unauthorized role → redirect to role-appropriate home or **403** page.

### 5.2 Lazy loading

- Code-split by route group to keep student check-in bundle minimal.
- Prefetch instructor session detail on list hover (optional; not required MVP).

---

## 6. Styling Architecture

### 6.1 Tailwind configuration

- `content`: `./src/**/*.{ts,tsx}`.
- `theme.extend`: map semantic colors to CSS variables from [04-design-tokens.md](./04-design-tokens.md).
- Breakpoints: `sm` 640, `md` 768, `lg` 1024, `xl` 1280 (default Tailwind).

### 6.2 Class composition

- Use `cn()` helper (clsx + tailwind-merge) for variant classes.
- Component variants via `class-variance-authority` (optional) or explicit variant maps — team choice at bootstrap; document in component file header.

### 6.3 Global styles (`globals.css`)

- Import token `:root` block.
- Base: `box-sizing`, font stack, body background.
- Focus-visible defaults for keyboard users.

---

## 7. Radix UI Usage

| Primitive | We Check usage |
| --- | --- |
| `Dialog` | Permission help, confirm delete/cancel session, manual edit |
| `DropdownMenu` | Row actions, user menu |
| `Toast` / Sonner | API success/error |
| `Tabs` | Session detail: QR / Monitor / Roster |
| `Tooltip` | Icon-only buttons, GPS radius help |
| `Select` | Status filter, role assignment |
| `Switch` | Active user toggle (admin) |
| `Label` + slot | Form field association |

Wrap each primitive once in `components/ui/*` — feature code imports wrappers only ([05-common-ui-components.md](./05-common-ui-components.md)).

---

## 8. Device Capabilities Integration

| Capability | API | UI hook / component |
| --- | --- | --- |
| QR scan | `BarcodeDetector`, `@zxing/browser` fallback | `QrScannerView` ([07-event-specific-components.md](./07-event-specific-components.md)) |
| GPS | `navigator.geolocation` | `useGeolocation` with 15 s timeout |
| Camera | `getUserMedia` | Permission modal + stream preview |
| Fullscreen | Fullscreen API | Instructor QR presentation mode |

Platform targets: **iOS 15+ Safari**, **Android 10+ Chrome** ([NFR-18](../brds/07-non-functional-risk.md)).

---

## 9. Polling and Live UI

| Surface | Interval | Query key |
| --- | --- | --- |
| QR token | 5 s | `['session', id, 'qr']` |
| Live attendance | 5 s while `Active` | `['session', id, 'attendance']` |
| Session list | 30 s on dashboard | `['sessions']` |

Display `isFetching` subtly — do not unmount QR between polls.

---

## 10. Internationalization

MVP uses **static Vietnamese strings** in `@wecheck/domain` and colocated `vi.ts` message files — no i18n framework required for pilot.

| Content type | Location |
| --- | --- |
| API error messages | `@wecheck/domain` `messages` |
| UI labels | Feature `copy.ts` or shared `copy/` module |
| Date/time | `Intl.DateTimeFormat('vi-VN', …)` |
| Numbers | `Intl.NumberFormat('vi-VN')` |

---

## 11. Testing (UI)

| Type | Tool | Scope |
| --- | --- | --- |
| Unit | Vitest + Testing Library | Components, hooks |
| Accessibility | jest-axe or axe-playwright | Login, check-in, QR |
| E2E | HTTP/browser suite | Critical paths per [11-testing-plan.md](../technical/11-testing-plan.md) |

---

## 12. Traceability

| Stack area | FR | NFR |
| --- | --- | --- |
| React mobile web | FR-07, FR-08 | NFR-17, NFR-18, NFR-19 |
| QR display | FR-06 | NFR-06, NFR-20 |
| TanStack Query polling | FR-15 | — |
| RBAC routes | FR-12, FR-13 | NFR-11 |
| Shared Zod forms | FR-04, FR-01 | — |

---

## 13. Future Consideration

- `openapi-typescript` generated API client.
- Storybook for component catalog.
- `@tanstack/react-router` migration if nested loaders needed.
- Service worker for static asset caching on student devices.
