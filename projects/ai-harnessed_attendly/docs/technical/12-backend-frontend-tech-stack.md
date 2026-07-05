# Attendly — Backend/Frontend Tech Stack

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-system-overview.md](./00-system-overview.md) · [02-module-breakdown.md](./02-module-breakdown.md) · [04-database-design.md](./04-database-design.md) · [05-api-design.md](./05-api-design.md) · [10-local-development-setup.md](./10-local-development-setup.md)

## 1. Purpose

This document defines the recommended MVP technology stack for Attendly backend and frontend, including rationale and constraints.

## 2. Stack selection principles

| ID | Principle | Rationale |
| --- | --- | --- |
| TS-01 | Prioritize predictable delivery over novelty | MVP timeline and operational simplicity |
| TS-02 | Optimize for API correctness and auditability | attendance is compliance-sensitive |
| TS-03 | Keep mobile-web UX fast and clear | student check-in is primary path |
| TS-04 | Use broadly supported tooling | easier hiring and maintenance |

## 3. Recommended backend stack

### 3.1 Runtime and framework

| Layer | Recommendation | Why |
| --- | --- | --- |
| Language | TypeScript | shared types with frontend |
| Runtime | Node.js 20 LTS | mature ecosystem and tooling |
| API framework | NestJS (or Express/Fastify with structured modules) | clear module boundaries and validation |
| Validation | Zod or class-validator | strict schema validation and typed DTOs |

### 3.2 Persistence and messaging

| Layer | Recommendation | Why |
| --- | --- | --- |
| Primary DB | PostgreSQL | strong relational integrity for attendance invariants |
| ORM/query | Prisma or TypeORM (or SQL-first approach) | migration support and productivity |
| Cache/pubsub | Redis (optional MVP, recommended for realtime) | session/channel updates and hot reads |
| Queue | lightweight job queue (Redis-backed) | export jobs and async processing |

### 3.3 Backend platform concerns

| Concern | Recommended approach |
| --- | --- |
| Auth | JWT-based access tokens with role/scope claims |
| RBAC | centralized authorization guard + scope resolver |
| Observability | structured JSON logging + metrics + tracing IDs |
| API docs | OpenAPI generation from source contracts |
| Testing | Jest/Vitest + supertest/integration DB harness |

## 4. Recommended frontend stack

### 4.1 Web UI stack

| Layer | Recommendation | Why |
| --- | --- | --- |
| Framework | React + TypeScript | mature ecosystem and strong DX |
| Build tool | Vite | fast local iteration |
| Routing | React Router | role-based route composition |
| Server-state | TanStack Query | robust API caching/retries |
| Forms/validation | React Hook Form + Zod | reliable input handling |

### 4.2 Next.js option boundary

`Next.js` is an acceptable frontend framework option when the team needs hybrid SSR/CSR pages, but MVP baseline remains client-first check-in delivery with minimal runtime complexity.

| Topic | Baseline choice | Next.js note |
| --- | --- | --- |
| Student check-in flow | client-rendered React routes | keep check-in path fast and deterministic if using Next.js |
| Staff dashboard pages | client-rendered list/detail pages | optional SSR for heavy report pages in Next.js |
| Deployment model | simple static + API split | Next.js app runtime is valid if operationally justified |
| MVP recommendation | React + Vite default | adopt Next.js only when clear FR/NFR benefit is documented |

### 4.3 UI implementation concerns

| Concern | Recommended approach |
| --- | --- |
| Styling | CSS variables + componentized design system integration |
| Accessibility | keyboard and contrast checks for lecturer/admin views |
| i18n | Vietnamese-first copy with key-based localization |
| Realtime updates | WebSocket or SSE for open-session roster |

### 4.4 Client-side QR libraries (`apps/web`)

Student scan and lecturer display both run in the browser. The web client uses two npm packages plus browser APIs — no native QR SDK or OS camera deep links.

| Concern | Package / API | Version | Primary component | Role |
| --- | --- | --- | --- | --- |
| QR decode (student) | [`jsqr`](https://www.npmjs.com/package/jsqr) | `^1.4.0` | `QrScannerPanel` (DC-13) | Decode QR payload from a live camera frame (`ImageData`) |
| QR encode (lecturer) | [`qrcode.react`](https://www.npmjs.com/package/qrcode.react) | `^4.2.0` | `QrDisplayPanel` (DC-01) | Render rotating session `qrPayload` as `QRCodeSVG` for dashboard and projection |
| Camera capture | `navigator.mediaDevices.getUserMedia` | Browser API | `QrScannerPanel` | Rear/environment camera stream (`facingMode: { ideal: "environment" }`) |
| Preview orientation | Browser `facingMode` + paired preview/decode flip | Internal policy | `QrScannerPanel` | Rear camera unmirrored; user/unknown cameras flipped consistently in preview and decode (see §4.4.1a) |
| Payload normalization | Internal helper | Internal | `QrScannerPanel` | Map decoded string to opaque `qrToken` for `POST /v1/check-ins` |

#### 4.4.1 Student decode pipeline (PG-02)

Trace: `FR-16`, `NFR-14`, DC-13 in [../ui-ux/07-domain-specific-components.md](../ui-ux/07-domain-specific-components.md).

**Camera stream**

1. Request `getUserMedia` with `facingMode: { ideal: "environment" }` (rear camera when available).
2. Retain the `MediaStream` across UI transitions from permission prompt to live preview — do not tie stream lifetime to a view that unmounts.
3. Attach the stream to the visible preview only after the scanning view is shown (`playsInline`, `muted`).

**Frame decode**

1. Sample frames from the live preview on a steady loop (e.g. `requestAnimationFrame`).
2. Decode each frame client-side into a raw payload string.
3. Normalize the payload to an opaque `qrToken` — see [05-api-design.md](./05-api-design.md) §5.3.
4. Submit token via `POST /v1/check-ins`; server validates TTL and session binding (M04).

**Preview orientation (NFR-14)**

Goal: the live preview matches real-world left/right alignment to a projected QR — not selfie-style mirroring.

1. Read `facingMode` from the active video track after the stream starts.
2. `environment` (rear): no horizontal transform on preview or decode.
3. `user` or omitted/`unknown` (typical laptop webcam fallback): apply the same horizontal flip to preview and decode together.
4. Never flip preview without flipping decode (or vice versa).

See [§4.4.1a](#441a-preview-orientation-policy-nfr-14) for device matrix and laptop behavior.

**Cleanup**

On stop or unmount: stop the decode loop, release all media tracks, and detach the stream from the preview.

#### 4.4.1a Preview orientation policy (NFR-14)

Portable design policy for in-browser QR scanning. Trace: `NFR-14`, `FR-16`.

##### Problem

The user aims a device at a displayed QR code (e.g. classroom projection). If the live preview is horizontally inverted (selfie-style), left/right movement feels reversed and alignment is harder. If the preview is flipped but the decode pipeline reads the raw camera frame, the decoder sees a different image than the user — a common cause of “QR visible on screen but never scans.”

**Design goal:** **natural world orientation** — moving the device left shifts the on-screen image left, matching alignment to a physical screen.

##### Decision rules

| `facingMode` (from active video track) | Preview | Decode pipeline |
| --- | --- | --- |
| `environment` (rear camera) | no horizontal flip | no horizontal flip |
| `user` (front / built-in webcam) | horizontal flip | same horizontal flip |
| omitted / unknown | treat as `user` | same horizontal flip |

Read `facingMode` once when the stream starts. Apply one mirror flag to **both** preview and decode for the whole session.

**Core invariant:** preview and decode must use the same orientation transform. Never flip one without the other.

##### Device matrix

| Device / camera | `getUserMedia` constraint | Typical `facingMode` | Policy |
| --- | --- | --- | --- |
| Phone rear camera (primary) | `ideal: "environment"` | `environment` | unmirrored |
| Phone front camera (fallback) | same; browser may pick front | `user` | mirrored |
| Laptop / desktop webcam | same; no rear camera | `user` or omitted | mirrored |
| External USB camera | same | often omitted | mirrored |

**Laptop note:** Desktop browsers accept the stream but often omit `facingMode` on built-in webcams. Treat omitted as `user` and mirror — built-in cameras usually need correction to match real-world left/right.

**Mobile note:** Product UX targets the rear-camera path (unmirrored). The `user` / unknown branch supports laptop dev, QA, and rare front-camera fallback without breaking decode.

##### Preview vs decode (conceptual)

```
Camera frames ──► [optional horizontal flip] ──► live preview (what user sees)
              └──► [same flip] ──► frame buffer ──► QR decoder
```

##### Verification (any stack)

- Rear / `environment` camera: preview not mirrored; moving device left moves image left.
- User / unknown / laptop webcam: preview mirrored; decode still succeeds on a valid QR.
- Mismatch symptom: preview looks correct but decode never succeeds — check that both paths share one mirror flag.

##### Known limitations

- Facing is evaluated once per stream; mid-session camera switches are not re-handled.
- `ideal: "environment"` does not fail on laptops — it silently falls back to the webcam.
- Portrait/landscape rotation is not separately corrected; moderate skew is tolerated, extreme angles may need reframing.
- Primary UX is mobile rear camera; laptop scanning is a supported dev/edge path, not the main product flow.

#### 4.4.2 Lecturer display pipeline (PG-05 / projection)

Trace: `FR-14`, `NFR-15`, DC-01.

1. `GET /v1/class-sessions/{id}/qr/current` returns `qrPayload`, `expiresAt`, and `tokenState`.
2. `QrDisplayPanel` renders `QRCodeSVG` with `level="M"`, white background, black modules.
3. Canvas size: `280px` in dashboard mode; `PROJECTION_QR_SIZE` (`432px`) in projection mode for 1280×720 legibility (`AC-UI-06`).
4. `QrCountdownRing` drives refresh before TTL expiry; manual **Làm mới mã QR** calls `onRefresh`.

Token signing, rotation, and validation remain server-side (M04). Client libraries only render or read the opaque `qrPayload` string.

#### 4.4.3 Library selection rationale

| Decision | Rationale |
| --- | --- |
| `jsqr` over WASM/native bridges | Pure JavaScript; works in mobile Safari/Chrome without extra binaries; frame-by-frame decode fits `getUserMedia` preview |
| `qrcode.react` over server-rendered images | SVG scales cleanly for projection; no round-trip per 30s rotation; React-friendly component API |
| No unified encode/decode package | Encode and decode run on different surfaces with different performance profiles; split keeps bundle lean on PG-02 |

## 5. Shared and cross-cutting stack

### 5.1 Shared libraries

| Library area | Recommendation |
| --- | --- |
| API types/contracts | shared TypeScript package for DTOs/enums |
| Error codes | shared constant catalog used by API and frontend |
| Date/time | `dayjs` or `date-fns` with UTC handling conventions |
| Validation schemas | shared domain enums and constraint definitions |

### 5.2 DevOps and quality tooling

| Area | Recommendation |
| --- | --- |
| Package manager | pnpm |
| Lint | ESLint + Prettier |
| Commit quality | conventional commit linting optional |
| CI | GitHub Actions (or equivalent) for lint/test/build gates |

### 5.3 Monorepo layout

| Package | Role |
| --- | --- |
| `apps/api` | Backend API — NestJS modules, domain services, integration test harness |
| `apps/web` | Frontend SPA — React routes, TanStack Query, QR components |
| `tests/playwright-ui` | Playwright browser tests — acceptance and regression scenarios |
| Shared types (optional) | `@attendly/contracts` or equivalent for DTOs and error codes |

Local and CI commands run from repository root via npm/pnpm workspace scripts (`dev:api`, `dev:web`, `test:integration`, `aih:check`).

## 6. Mapping stack to module architecture

| Module | Primary stack component |
| --- | --- |
| Identity and Access | backend auth module + JWT guards |
| Session Lifecycle | backend domain service + DB transaction |
| Check-in Orchestrator | backend command handler + validation layer |
| Attendance Ledger | backend persistence + audit event hooks |
| Reporting and Export | query service + async job worker |
| Realtime Delivery | Redis pubsub + websocket gateway |
| Frontend student flow | React mobile web check-in pages |
| Frontend staff flow | React admin/lecturer dashboards |

## 7. Versioning and compatibility policy

### 7.1 API compatibility

- API version prefix (`/v1`) required.
- Breaking API changes require new version path or migration strategy.
- Error codes are treated as contract and should not be renamed casually.

### 7.2 Browser support target

- iOS Safari (current major versions used by students)
- Android Chrome (current major versions used by students)
- Chromium-based desktop browser for staff dashboards

## 8. Security and compliance baseline in stack choices

| Requirement | Stack implication |
| --- | --- |
| NFR-08 secure transport | TLS termination in all non-local envs |
| NFR-09 RBAC | scope-aware middleware and query filtering |
| NFR-10 auditability | append-only audit service and immutable writes |
| NFR-11/12 GPS minimization | optional GPS fields and retention jobs |

## 9. MVP stack decision summary

### 9.1 Recommended baseline

- **Backend:** Node.js 20 + TypeScript + NestJS/Fastify + PostgreSQL + optional Redis
- **Frontend:** React + TypeScript + Vite + TanStack Query
- **Testing:** Jest/Vitest + integration DB tests + E2E browser tests
- **Infra for local/dev:** Docker Compose for DB/cache/runtime dependencies

### 9.2 Out-of-scope stack additions for MVP

- Native mobile frameworks.
- Complex event streaming platforms.
- Multi-region distributed data stores.

## 10. Traceability to requirements

| Stack decision area | FR/BR alignment | NFR alignment |
| --- | --- | --- |
| Session and check-in APIs on typed backend modules | FR-07, FR-08, FR-11, FR-16, FR-22, FR-23; BR-01 to BR-04, BR-23 | NFR-01, NFR-03, NFR-06 |
| Transactional relational persistence | FR-18, FR-20, FR-21, FR-29 | NFR-07, NFR-10, NFR-13 |
| Centralized auth + RBAC guards | FR-15, FR-27, FR-28, FR-32; BR-18, BR-19 | NFR-09 |
| Optional cache/pubsub for realtime and burst handling | FR-19, FR-14 | NFR-01, NFR-16 |
| Mobile-web-first frontend stack | FR-16, FR-34, FR-35, FR-37 | NFR-14, NFR-11 |
| Client QR libraries (`jsqr`, `qrcode.react`) | FR-14, FR-16 | NFR-14, NFR-15 |
| Async export/job capabilities | FR-27, FR-30 | NFR-16, NFR-17 |

## 11. Technology decision records (MVP)

| TDR ID | Decision | Alternatives considered | Decision status |
| --- | --- | --- | --- |
| TDR-01 | Use TypeScript end-to-end for backend and frontend | Mixed-language stack | Approved |
| TDR-02 | Use PostgreSQL as source of truth for attendance data | NoSQL-first model | Approved |
| TDR-03 | Use React + Vite for web clients | heavier SSR-first runtime | Approved |
| TDR-04 | Keep Redis optional for MVP baseline, recommended for realtime | mandatory cache cluster | Approved |
| TDR-05 | Keep API contract versioned at `/v1` with stable error codes | unversioned endpoints | Approved |
| TDR-06 | Use `jsqr` + `qrcode.react` for client QR decode/display | native scanner SDK, server-rendered QR images | Approved |

## 12. Future consideration

- SSO/MFA integration middleware and identity federation adapters.
- Dedicated analytics store for attendance trend modeling.
- Edge caching strategy for high-scale multi-campus deployments.

## 13. MVP boundary note

- Stack choices in this document prioritize delivery of MVP Must capabilities first; Should-scope capabilities (for example advanced policy tooling and extended anti-fraud signals) must not introduce mandatory platform complexity for initial release.
- Technology decisions must preserve the canonical check-in model: session-bound short-lived multi-use QR and one successful attendance record per student/session.

## 14. Stack governance checklist

| Decision gate | Required confirmation |
| --- | --- |
| New dependency proposal | clear mapping to one or more FR/BR/NFR items |
| Runtime/framework change | no regression to check-in latency and idempotency guarantees |
| Frontend library change | mobile-web check-in UX remains first-class on target browsers |
| Infra/tooling addition | local onboarding complexity does not increase for MVP baseline |
