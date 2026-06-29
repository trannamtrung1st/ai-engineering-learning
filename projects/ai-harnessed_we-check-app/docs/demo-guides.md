# We Check — Demo & Manual Testing Guide

How to run the local preview stack, rehearse end-to-end demo scripts for stakeholders, and walk through individual flows using seeded demo accounts.

**Related:** [Local development setup](./technical/10-local-development-setup.md) · [Preview seed source](../apps/api/src/infra/preview-seed.ts)

---

## Contents

1. [Start the stack](#1-start-the-stack)
2. [Pre-demo checklist](#2-pre-demo-checklist)
3. [End-to-end demo scripts](#3-end-to-end-demo-scripts) ← **start here for live demos**
4. [Demo user credentials](#4-demo-user-credentials)
5. [Seeded preview data](#5-seeded-preview-data)
6. [Flow reference (step-by-step)](#6-flow-reference-step-by-step)
7. [Preview simulation query params](#7-preview-simulation-query-params)
8. [Check-in outcome codes](#8-check-in-outcome-codes)
9. [Mobile / remote testing](#9-mobile--remote-testing)
10. [Troubleshooting](#10-troubleshooting)
11. [Quick smoke checklist](#11-quick-smoke-checklist)

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

## 2. Pre-demo checklist

Run through this **5 minutes before** any live demo.

| Step | Action | Pass? |
| --- | --- | --- |
| 1 | `npm run aih:preview:verify` or open `/api/v1/health` → `ok` + `db: connected` | ☐ |
| 2 | Open `http://localhost:3007/login` — page loads | ☐ |
| 3 | Log in as instructor — lands on `/sessions` with **SWE-101 — Buổi 5** (Active) | ☐ |
| 4 | Open `/sessions/sess-1?tab=monitor` — spoof badge + code-sharing alert visible | ☐ |
| 5 | In a **second browser profile** (incognito), log in as student and open the happy-path check-in URL (see [§3](#3-end-to-end-demo-scripts)) | ☐ |

### Browser layout (desktop demo)

Use **two isolated sessions** so roles do not share cookies:

| Window | Profile | Role | Bookmark |
| --- | --- | --- | --- |
| **Left / projector** | Normal Chrome | Instructor | `/sessions/sess-1/qr-present` |
| **Right / laptop** | Incognito | Student | `/check-in?token=valid-token-id&gpsSim=delay&cameraSim=grant` |

> Tip: resize windows side-by-side. The instructor monitor tab polls every ~5 s — leave it open while the student checks in to show the live count update.

### Demo bookmark URLs

Save these in your browser for one-click access during demos:

```
http://localhost:3007/sessions/sess-1/qr-present
http://localhost:3007/sessions/sess-1?tab=monitor
http://localhost:3007/check-in?token=valid-token-id&gpsSim=delay&cameraSim=grant
http://localhost:3007/check-in?token=stale-token-id&gpsSim=delay
http://localhost:3007/check-in?token=consumed-token-id&gpsSim=delay
http://localhost:3007/check-in?demo=outcomes
http://localhost:3007/admin/reports
```

### Reset fixtures between rehearsals

If a prior run consumed tokens or changed session state:

```bash
npm run aih:preview:down
npm run aih:preview
```

---

## 3. End-to-end demo scripts

Curated narratives for presenting to others. Each script lists **who logs in where**, **what to say**, and **what the audience should see**.

---

### Script A — "A typical class session" (~8 min)

**Audience:** Faculty, workshop organizers  
**Goal:** Show the happy path — QR display → student check-in → live monitor → personal history  
**Setup:** Two browser windows (instructor + student incognito)

| # | Actor | Action | What to highlight |
| --- | --- | --- | --- |
| 1 | **You** | Open projector on `/sessions/sess-1/qr-present` | Fullscreen rotating QR with ~30 s countdown — *"Mã xoay liên tục, không thể chụp màn hình gửi cho bạn bè"* |
| 2 | **You** | Press `Esc`, switch to **Theo dõi** tab on `/sessions/sess-1` | Present / pending / absent summary — *"Giảng viên thấy ai đã điểm danh theo thời gian thực"* |
| 3 | **Student window** | Log in `student@example.edu.vn` / `StudentPass8` | Lands on `/check-in` |
| 4 | **Student window** | Open `/check-in?token=valid-token-id&gpsSim=delay&cameraSim=grant` → submit | **Điểm danh thành công** — *"Sinh viên chỉ cần trình duyệt điện thoại, không cần cài app"* |
| 5 | **Instructor window** | Wait ~5 s on monitor tab | Student A moves from **Chưa** → **Đã điểm danh** |
| 6 | **Student window** | Navigate to **Lịch sử** (`/history`) | Past session **NET-301 — Buổi 1** with **Có mặt** badge — *"Sinh viên tự tra cứu lịch sử chuyên cần"* |

**Closing line:** *"Toàn bộ buổi điểm danh hoàn tất trong dưới 5 phút thay vì 15–30 phút gọi tên thủ công."*

---

### Script B — "Anti-fraud & policy enforcement" (~10 min)

**Audience:** Phòng đào tạo, security-minded stakeholders  
**Goal:** Demonstrate layered fraud prevention (enrollment, GPS, one-time token, spoof detection)  
**Setup:** Student incognito window; instructor monitor already open on `/sessions/sess-1?tab=monitor`

| # | Actor | Action | What to highlight |
| --- | --- | --- | --- |
| 1 | **You** | Point at monitor — spoof badge on **Lê Văn C** + code-sharing alert | Pre-seeded **SpoofSuspected** + **TokenReuseAlert** — *"Hệ thống cảnh báo giảng viên ngay, không cần đối soát thủ công"* |
| 2 | **Student window** | Log in `studentb@example.edu.vn` → `/check-in?token=valid-token-id&gpsSim=delay` | **Không trong danh sách** (`NotEnrolled`) — *"Chỉ sinh viên đăng ký môn mới điểm danh được"* |
| 3 | **Student window** | Log out → log in `studentc@example.edu.vn` → same URL with `gpsLat=10.764122&gpsLng=106.660172` | **Ngoài phạm vi phòng học** (`OutOfRadius`) — *"GPS xác minh sinh viên thực sự ở trong lớp (~100 m)"* |
| 4 | **Student window** | Open `/check-in?token=stale-token-id&gpsSim=delay` | **Mã QR đã hết hạn** — *"Mã chỉ có hiệu lực 30 giây"* |
| 5 | **Student window** | Open `/check-in?token=consumed-token-id&gpsSim=delay` | **Mã QR đã được sử dụng** — *"Mỗi mã chỉ dùng một lần — chống chia sẻ QR"* |
| 6 | **Student window** | Log in `student@example.edu.vn` → check in on `valid-token-id` again | **Đã điểm danh** (`DuplicateCheckIn`) — *"Một tài khoản, một lần/buổi"* |
| 7 | **You** | Open `/login` → `deactivated@example.edu.vn` / `StudentPass8` | Login blocked — *"Tài khoản vô hiệu hóa không thể điểm danh"* |

**Optional finale:** Open `/check-in?demo=outcomes` to flash all outcome screens in one page.

**Closing line:** *"Ba lớp bảo vệ: xác thực danh tính + vị trí GPS + token QR một lần dùng."*

---

### Script C — "Training office overview" (~5 min)

**Audience:** Phòng đào tạo admin  
**Goal:** Institution-wide visibility, data export, roster onboarding  
**Setup:** Single admin browser window

| # | Action | What to highlight |
| --- | --- | --- |
| 1 | Log in `admin@example.edu.vn` / `AdminPass123` → `/admin/reports` | Summary cards + session table — *"Tổng quan toàn trường, không chỉ từng lớp"* |
| 2 | Show filter bar (class / subject / date range) | Drill-down capability (UI shell) |
| 3 | Navigate to `/admin/export` → apply filters → **Xuất CSV** | Demo toast on success — *"Xuất dữ liệu cho hệ thống học vụ hiện có"* |
| 4 | Log out → log in as instructor → visit `/admin/export` | Denied: *"Chỉ phòng đào tạo mới có quyền xuất dữ liệu"* — RBAC |
| 5 | Back as admin → `/admin/rosters/import` | Drag-and-drop CSV upload — *"Import danh sách lớp từ file CSV"* |
| 6 | Show `?view=complete` on import page | Success summary state |

**Closing line:** *"Phòng đào tạo kiểm soát dữ liệu tập trung; giảng viên chỉ xem báo cáo lớp mình."*

---

### Script D — "3-minute executive pitch"

**Audience:** Leadership, sponsors — very short attention span  
**Goal:** Hit the three value props fast  
**Setup:** Pre-open tabs before the meeting

| Tab | URL | Show for |
| --- | --- | --- |
| 1 | `/sessions/sess-1/qr-present` | 30 s — rotating QR on projector |
| 2 | `/check-in?token=valid-token-id&gpsSim=delay&cameraSim=grant` (student incognito, pre-logged-in) | 30 s — tap submit → **Điểm danh thành công** |
| 3 | `/sessions/sess-1?tab=monitor` | 30 s — live count updates |
| 4 | `/check-in?demo=outcomes` | 30 s — scroll through fraud rejection screens |
| 5 | `/admin/reports` | 30 s — institution dashboard |

**Talking track (60 s each):**

1. *"Sinh viên quét QR động — không app, không giấy tờ."*
2. *"Giảng viên theo dõi realtime — biết ai vắng ngay trong buổi học."*
3. *"Hệ thống tự chặn gian lận GPS, chia sẻ mã, điểm danh hộ."*

---

### Script E — "Full session lifecycle" (~12 min)

**Audience:** Technical evaluators, QA, product reviewers  
**Goal:** Walk through every session state and role transition  
**Setup:** Instructor window + student incognito

| # | Actor | Action | Expected state |
| --- | --- | --- | --- |
| 1 | Instructor | `/sessions` — note **Active**, **Draft**, **Closed** sections | Three lifecycle states visible |
| 2 | Instructor | Open `/sessions/sess-2` (Draft) → **Cài đặt** → **Mở buổi học** | Session opens; QR + monitor tabs appear |
| 3 | Instructor | Switch to **Mã QR** → **Trình chiếu QR** | Fullscreen presentation mode |
| 4 | Student | Check in on active `sess-1` with `valid-token-id` | Present |
| 5 | Instructor | `/sessions/sess-1/monitor` (dedicated route) | Same dashboard, projector-friendly URL |
| 6 | Instructor | `/reports` — apply class/subject filters | Instructor-scoped reports |
| 7 | Instructor | Open `/sessions/sess-3` (Closed) | Info alert: session ended, data frozen |
| 8 | Student | `/history` | Closed session **NET-301** with timestamp |
| 9 | You | While logged out, open `/check-in?token=valid-token-id` | Redirect to `/login?returnUrl=…` → login → returns to check-in |

---

### Script F — "Mobile / real-device demo" (~8 min)

**Audience:** Anyone who needs to see real camera + GPS  
**Goal:** Prove the mobile web path works outside desktop simulation  
**Setup:** ngrok tunnel + instructor laptop + your phone

| # | Action |
| --- | --- |
| 1 | `ngrok http 3007` — note the HTTPS URL |
| 2 | Instructor laptop: `{ngrok-url}/sessions/sess-1/qr-present` on projector |
| 3 | Phone: open `{ngrok-url}/login` → `student@example.edu.vn` / `StudentPass8` |
| 4 | Scan the live QR with phone camera → deep link opens `/check-in?token=…` |
| 5 | Grant camera + location permissions → submit → **Điểm danh thành công** |
| 6 | Instructor monitor updates within ~5 s |

> If ngrok is unavailable, use `http://<your-lan-ip>:3007` on the same Wi-Fi.

---

### Choosing a script

| If your audience cares about… | Use |
| --- | --- |
| Day-to-day classroom workflow | **Script A** |
| Fraud prevention & policy | **Script B** |
| Admin / institutional reporting | **Script C** |
| Quick sponsor pitch | **Script D** |
| Complete product walkthrough | **Script E** |
| Real phone camera + GPS | **Script F** |

---

## 4. Demo user credentials

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

## 5. Seeded preview data

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

> Preview tokens auto-refresh every ~20 s while the stack runs. Use aliases (`valid-token-id`) rather than copying UUIDs from an old tab.

---

## 6. Flow reference (step-by-step)

Detailed steps for manual testing and ad-hoc exploration. For live demos, prefer the scripted flows in [§3](#3-end-to-end-demo-scripts).

### 6.1 Authentication

**Happy path — login per role**

1. Open `http://localhost:3007/login`
2. Sign in with any credential row from §4
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

### 6.2 Instructor — session management

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

### 6.3 Student — QR check-in

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
- `/check-in?outcome=Present` — single outcome preview (replace `Present` with any code from §8)

---

### 6.4 Student — attendance history

Login: `student@example.edu.vn` / `StudentPass8`

1. Go to `/history` (or bottom nav **Lịch sử**)
2. See closed session **NET-301 — Buổi 1** with **Có mặt** badge and check-in timestamp

**Empty history**

1. Login as `studentb@example.edu.vn`
2. Go to `/history`
3. Expect empty state: *"Chưa có buổi học nào"*

---

### 6.5 Admin — reports, export, roster import

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

### 6.6 Instructor live monitor — security alerts

Login as instructor, open active session monitor:

`/sessions/sess-1?tab=monitor`

Seeded data includes:

- **SpoofSuspected** attempt from `studentc@example.edu.vn` (mock location flag)
- **TokenReuseAlert** on consumed QR token

The monitor polls every ~5 s and shows spoof badge + code-sharing warning when API alerts are present.

---

## 7. Preview simulation query params

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

## 8. Check-in outcome codes

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

## 9. Mobile / remote testing

1. Start preview stack on your machine
2. Tunnel web port: `ngrok http 3007`
3. On phone, open the ngrok HTTPS URL (Vite `allowedHosts: true` permits tunnel hosts)
4. Test check-in with real camera + GPS

For LAN testing without ngrok, use `http://<your-lan-ip>:3007` on the same Wi-Fi network.

See [Script F](#script-f--mobile--real-device-demo-8-min) for a full mobile demo narrative.

---

## 10. Troubleshooting

| Problem | Fix |
| --- | --- |
| Login works but no sessions | Confirm `SEED_ENABLED=true` and API logs show preview seed applied |
| Check-in token always expired | Preview tokens refresh every ~20 s; use `valid-token-id` alias or scan live QR |
| CORS errors | Ensure `CORS_ORIGIN` in `.env` matches web URL (`http://localhost:3007`) |
| Web on wrong port | Check `WEB_PORT` in `.env`; restart dev server |
| Database connection failed | `npm run aih:dev:db:up` and verify `DATABASE_URL` |
| Demo state "dirty" after rehearsal | `npm run aih:preview:down && npm run aih:preview` |
| Monitor alerts missing | Open `/sessions/sess-1?tab=monitor` and wait one poll cycle (~5 s) |

**Reset preview fixtures:**

```bash
npm run aih:preview:down
npm run aih:preview
```

---

## 11. Quick smoke checklist

- [ ] API health returns `ok` + `db: connected`
- [ ] Admin login → `/admin/users`
- [ ] Instructor login → `/sessions` → open `sess-1` monitor
- [ ] Student login → `/check-in?token=valid-token-id&gpsSim=delay` → Present
- [ ] `studentb` → NotEnrolled on valid token
- [ ] `deactivated@example.edu.vn` → login blocked
- [ ] `/history` shows closed session for student A
- [ ] Instructor denied on `/admin/export`
