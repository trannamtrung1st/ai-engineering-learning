# We Check — Demo & Manual Testing Guide

Overview of how to run the local preview stack and walk through the main application flows using seeded demo accounts.

**Related:** [Local development setup](./technical/10-local-development-setup.md) · [Preview seed source](../apps/api/src/infra/preview-seed.ts)

---

## 1. Start the stack

### Prerequisites

- Docker running (PostgreSQL on port `5432`)
- Root `.env` copied from `.env.example` with `SEED_ENABLED=true`

### Quick start (recommended)

```bash
npm run aih:dev:db:up          # start Postgres
npm run aih:preview            # API + web with preview seed
```

Verify:

| Service | URL | Expected |
| --- | --- | --- |
| Web | `http://localhost:3007` | Login page (or home shell) |
| API health | `http://localhost:3001/api/v1/health` | `{ "status": "ok", "db": "connected" }` |
| Proxied API (via Vite) | `http://localhost:3007/api/v1/health` | Same health response |

> **Port note:** Local web defaults to **3007** (`WEB_PORT` in `.env`). API stays on **3001**. If you tunnel with ngrok, use `ngrok http 3007`.

### Alternative: run services separately

```bash
npm run aih:dev:db:up
npm run dev --workspace @wecheck/api    # terminal 1
npm run dev --workspace @wecheck/web    # terminal 2
```

Preview seed data loads automatically when `SEED_ENABLED=true` on API startup.

---

## 2. Demo user credentials

All passwords are deterministic preview fixtures — safe for local/dev only.

| Role | Display name | Email | Password | Institutional ID | Notes |
| --- | --- | --- | --- | --- | --- |
| **Training office admin** | Quản trị viên Phòng đào tạo | `admin@example.edu.vn` | `AdminPass123` | ADMIN001 | Full admin access |
| **Instructor** | Giảng viên Nguyễn Văn B | `instructor@example.edu.vn` | `InstructorPass8` | GV2026001 | Sessions, QR, monitor |
| **Student (enrolled)** | Sinh viên Nguyễn Văn A | `student@example.edu.vn` | `StudentPass8` | SV2026001 | Primary happy-path student |
| **Student (not enrolled)** | Sinh viên Trần Thị B | `studentb@example.edu.vn` | `StudentPass8` | SV2026002 | Triggers `NotEnrolled` |
| **Student (out of radius)** | Sinh viên Lê Văn C | `studentc@example.edu.vn` | `StudentPass8` | SV2026003 | Use with GPS override |
| **Student (deactivated)** | Sinh viên Võ Văn D | `deactivated@example.edu.vn` | `StudentPass8` | SV2026099 | Login blocked |

### Post-login landing pages

| Role | Default redirect |
| --- | --- |
| Student | `/check-in` |
| Instructor | `/sessions` |
| Admin | `/admin/users` |

---

## 3. Seeded preview data

### Classes & subject

| Entity | Code | Name |
| --- | --- | --- |
| Class A | HESD-01 | HESD Cohort A |
| Class B | HESD-02 | HESD Cohort B |
| Subject | SWE-101 | Software Engineering 101 |

Instructor **Nguyễn Văn B** is assigned to **HESD-01 / SWE-101**.  
Student **Nguyễn Văn A** and **Lê Văn C** are enrolled; **Trần Thị B** is deliberately **not** enrolled.

### Sessions

URL aliases (friendly IDs) resolve to real UUIDs in the database.

| Alias | Title | Status | Room | URL |
| --- | --- | --- | --- | --- |
| `sess-1` | SWE-101 — Buổi 5 | **Active** | Phòng A201 | `/sessions/sess-1` |
| `sess-2` | DB-201 — Buổi 3 | **Draft** | Phòng B102 | `/sessions/sess-2` |
| `sess-3` | NET-301 — Buổi 1 | **Closed** | Phòng C301 | `/sessions/sess-3` |

**Room GPS (all preview sessions):** `10.762622, 106.660172` (Ho Chi Minh City test coordinates), radius **100 m**.

### QR token fixtures (active session)

| Alias | Status | Purpose |
| --- | --- | --- |
| `valid-token-id` | Valid | Successful check-in |
| `stale-token-id` | Expired | `ExpiredQr` outcome |
| `consumed-token-id` | Consumed | `TokenAlreadyUsed` / duplicate scan |

Deep link format: `/check-in?token=<alias-or-uuid>`

---

## 4. Main flows

### 4.1 Authentication

**Happy path — login per role**

1. Open `http://localhost:3007/login`
2. Sign in with any credential row from §2
3. Confirm redirect to the role home (see table above)

**Invalid credentials**

1. Enter wrong password for `student@example.edu.vn`
2. Expect alert: *"Email hoặc mật khẩu không đúng"*

**Deactivated account**

1. Login as `deactivated@example.edu.vn` / `StudentPass8`
2. Expect alert: *"Tài khoản đã bị vô hiệu hóa"*

**Protected route redirect**

1. While logged out, open `/check-in?token=valid-token-id`
2. Expect redirect to `/login?returnUrl=…`
3. Login as `student@example.edu.vn` → returns to check-in flow

**Session expired**

1. Open `/login?sessionExpired=1`
2. Expect toast + alert: *"Phiên đăng nhập đã hết hạn"*

---

### 4.2 Instructor — session management

Login: `instructor@example.edu.vn` / `InstructorPass8`

**Session list**

1. Go to `/sessions`
2. See sections for Active, Draft, and Closed sessions
3. Click **Tạo buổi học** → `/sessions/new` to create a new session (form shell)

**Active session — monitor & QR**

1. Open `/sessions/sess-1` (SWE-101 — Buổi 5)
2. Default tab for Active sessions: **Theo dõi** (live attendance monitor)
3. Switch tabs:
   - **Mã QR** — rotating QR with countdown (~30 s cycle)
   - **Theo dõi** — present / pending / absent summary + student list
   - **Danh sách** — roster view
   - **Cài đặt** — session settings + lifecycle actions
4. Click **Trình chiếu QR** → fullscreen `/sessions/sess-1/qr-present` (press `Esc` to exit)

**Dedicated monitor route**

- `/sessions/sess-1/monitor` — same monitor dashboard on its own page

**Draft session — open for check-in**

1. Open `/sessions/sess-2` (Draft)
2. On **Cài đặt** tab, use lifecycle actions to **open** the session
3. After opening, tabs switch to monitor/QR; students can check in

**Closed session**

1. Open `/sessions/sess-3`
2. Monitor tab shows info alert: session ended, data no longer updates

**Instructor reports (shell)**

- `/reports` — filter bar for class/subject; apply filters to load data

---

### 4.3 Student — QR check-in

Login: `student@example.edu.vn` / `StudentPass8` (unless testing deep-link login redirect)

**Successful check-in (desktop sim)**

1. Open  
   `http://localhost:3007/check-in?token=valid-token-id&gpsSim=delay&cameraSim=grant`
2. Grant location when prompted (or rely on `gpsSim=delay` for in-room coordinates)
3. Confirm check-in → outcome **Điểm danh thành công** (`Present`)

**Check-in from instructor QR (real device)**

1. Instructor displays QR at `/sessions/sess-1/qr-present`
2. Student scans with phone camera (same Wi-Fi or ngrok tunnel)
3. Deep link opens `/check-in?token=<live-token-id>`
4. Student grants camera + GPS → submit

**Expired QR**

1. As student, open `/check-in?token=stale-token-id&gpsSim=delay`
2. Expect **Mã QR đã hết hạn** (`ExpiredQr`) + **Quét lại** button

**Token already used**

1. Open `/check-in?token=consumed-token-id&gpsSim=delay`
2. Expect **Mã QR đã được sử dụng** (`TokenAlreadyUsed`)

**Not enrolled**

1. Login as `studentb@example.edu.vn`
2. Open `/check-in?token=valid-token-id&gpsSim=delay`
3. Expect **Không trong danh sách** (`NotEnrolled`)

**Out of radius**

1. Login as `studentc@example.edu.vn`
2. Open  
   `/check-in?token=valid-token-id&gpsLat=10.764122&gpsLng=106.660172`  
   (coordinates ~170 m from room center)
3. Expect **Ngoài phạm vi phòng học** (`OutOfRadius`)

**Duplicate check-in**

1. As `student@example.edu.vn`, check in successfully on `valid-token-id`
2. Submit again on the same session (or use consumed token flow)
3. Expect **Đã điểm danh** (`DuplicateCheckIn`) with **Xem lịch sử** link

**View all outcome screens (no API)**

- `/check-in?demo=outcomes` — showcase of every check-in outcome panel
- `/check-in?outcome=Present` — single outcome preview (replace `Present` with any code from §6)

---

### 4.4 Student — attendance history

Login: `student@example.edu.vn` / `StudentPass8`

1. Go to `/history` (or bottom nav **Lịch sử**)
2. See closed session **NET-301 — Buổi 1** with **Có mặt** badge and check-in timestamp

**Empty history**

1. Login as `studentb@example.edu.vn`
2. Go to `/history`
3. Expect empty state: *"Chưa có buổi học nào"*

---

### 4.5 Admin — reports, export, roster import

Login: `admin@example.edu.vn` / `AdminPass123`

**Institution reports**

1. `/admin/reports` — populated summary cards + session table (default)
2. Alternate UI states via query param:
   - `?view=empty` — no results
   - `?view=error` — load error + retry
   - `?view=initial` — filter prompt only

**CSV export**

1. `/admin/export` — filter + **Xuất CSV** button (demo toast on success)
2. Login as **instructor** and visit `/admin/export` → denied message: *"Chỉ phòng đào tạo mới có quyền xuất dữ liệu"*

**Roster CSV import**

1. `/admin/rosters/import` — drag-and-drop CSV upload zone
2. UI state previews:
   - `?view=parsing` — spinner
   - `?view=error` — invalid format alert
   - `?view=complete` — success summary

**Placeholder admin pages**

- `/admin/users`, `/admin/rosters`, `/admin/policy` — shell placeholders for upcoming slices

---

### 4.6 Instructor live monitor — security alerts

Login as instructor, open active session monitor:

`/sessions/sess-1?tab=monitor`

Seeded data includes:

- **SpoofSuspected** attempt from `studentc@example.edu.vn` (mock location flag)
- **TokenReuseAlert** on consumed QR token

The monitor polls every ~5 s and shows spoof badge + code-sharing warning when API alerts are present.

---

## 5. Preview simulation query params

Use these on desktop browsers when real GPS/camera is unavailable. Append to any `/check-in` URL.

| Param | Values | Effect |
| --- | --- | --- |
| `gpsSim` | `delay` | Resolves in-room GPS after short delay |
| | `timeout` | GPS timeout → `GpsDisabled` |
| | `hang` | Keeps submit disabled (*Cần bật GPS*) until resolved |
| | `deny` / `deny-once` | Permission denied flow + guide modal |
| | `unavailable` | Geolocation unavailable |
| `gpsLat` / `gpsLng` | decimals | Override coordinates (e.g. out-of-radius test) |
| `gpsTimeoutMs` | `500` | Shorten GPS wait for faster tests |
| `gpsDelayMs` | `1500` | Delay before auto-GPS on deep link |
| `cameraSim` | `grant` / `deny` | Simulate camera permission |
| `scannerOnly` | `1` | Force QR scanner step even with `?token=` |
| `clearConsent` | `1` | Reset camera consent banner on entry |
| `mockLocation` | `1` | Send spoof flag → `SpoofSuspected` |
| `platform` | `ios` / `android` | Permission guide copy variant |
| `unsupportedBrowser` | `1` | Unsupported-browser gate |
| `expireSessionOnSubmit` | `1` | Expire session on submit → login redirect |

**Example — full desktop happy path:**

```
http://localhost:3007/check-in?token=valid-token-id&gpsSim=delay&cameraSim=grant
```

**Example — GPS disabled:**

```
http://localhost:3007/check-in?token=valid-token-id&gpsSim=timeout&gpsTimeoutMs=500
```

---

## 6. Check-in outcome codes

For `?outcome=<code>` previews and API responses:

| Code | Vietnamese title |
| --- | --- |
| `Present` | Điểm danh thành công |
| `ExpiredQr` | Mã QR đã hết hạn |
| `TokenAlreadyUsed` | Mã QR đã được sử dụng |
| `OutOfRadius` | Ngoài phạm vi phòng học |
| `GpsDisabled` | GPS chưa bật |
| `DuplicateCheckIn` | Đã điểm danh |
| `SpoofSuspected` | Cảnh báo bảo mật |
| `SessionNotActive` | Buổi học chưa mở |
| `NotEnrolled` | Không trong danh sách |
| `NetworkError` | Lỗi kết nối |

---

## 7. Mobile / remote testing

1. Start preview stack on your machine
2. Tunnel web port: `ngrok http 3007`
3. On phone, open the ngrok HTTPS URL (Vite `allowedHosts: true` permits tunnel hosts)
4. Test check-in with real camera + GPS

For LAN testing without ngrok, use `http://<your-lan-ip>:3007` on the same Wi-Fi network.

---

## 8. Troubleshooting

| Problem | Fix |
| --- | --- |
| Login works but no sessions | Confirm `SEED_ENABLED=true` and API logs show preview seed applied |
| Check-in token always expired | Preview tokens refresh every ~20 s; use `valid-token-id` alias or scan live QR |
| CORS errors | Ensure `CORS_ORIGIN` in `.env` matches web URL (`http://localhost:3007`) |
| Web on wrong port | Check `WEB_PORT` in `.env`; restart dev server |
| Database connection failed | `npm run aih:dev:db:up` and verify `DATABASE_URL` |

**Reset preview fixtures:**

```bash
npm run aih:preview:down
npm run aih:preview
```

---

## 9. Quick smoke checklist

- [ ] API health returns `ok` + `db: connected`
- [ ] Admin login → `/admin/users`
- [ ] Instructor login → `/sessions` → open `sess-1` monitor
- [ ] Student login → `/check-in?token=valid-token-id&gpsSim=delay` → Present
- [ ] `studentb` → NotEnrolled on valid token
- [ ] `deactivated@example.edu.vn` → login blocked
- [ ] `/history` shows closed session for student A
- [ ] Instructor denied on `/admin/export`
