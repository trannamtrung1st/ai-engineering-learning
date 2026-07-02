# Epic 3: Instructor Session Setup & Live QR Display

Instructor can create, configure, activate a workshop session and project a rotating QR code.

### Story 3.1: Instructor Dashboard and Session List

As an Instructor,
I want a dashboard listing my upcoming, active, and past workshop sessions,
So that I can quickly find and manage the session I am running today.

**Acceptance Criteria:**

**Given** a signed-in Instructor
**When** they navigate to the Instructor dashboard
**Then** sessions are grouped or filterable as upcoming, active, and past (UX-DR21)
**And** each session row shows title, scheduled date/time, and current lifecycle status
**And** quick actions are available to open session detail for active sessions (QR Display, Live Dashboard)

### Story 3.2: Create and Edit Workshop Session

As an Instructor,
I want to create a workshop session with title, scheduled date/time, and a bound Cohort Roster,
So that attendance is tracked against the correct student list.

**Acceptance Criteria:**

**Given** migrations for `workshop_sessions` table and at least one existing Cohort Roster
**When** an Instructor submits a new session with title, scheduled date/time, and roster selection
**Then** a session is created in **draft** state via `api/src/domain/sessions/` (FR7, AD-3, AD-15)
**When** they edit an existing draft or scheduled session
**Then** title, date/time, and roster binding can be updated
**When** a session has no bound roster
**Then** activation is blocked with a message to bind a roster (FR7, UX-DR31)

### Story 3.3: Geofence Configuration

As an Instructor,
I want to set the geofence center and radius for a workshop session,
So that check-in is validated against the correct classroom location.

**Acceptance Criteria:**

**Given** an Instructor on session create/edit
**When** they set geofence center via map pin drag or "Use my location" (UX-DR12)
**And** they set radius between 50–200 m (default 100 m when not specified)
**Then** `geofence_lat`, `geofence_lng`, and `radius_m` are saved on the session (FR8)
**And** the saved geofence is used for all Check-In Attempts on that session (FR8)
**When** geofence is not configured
**Then** session cannot transition to **active** (FR7, FR9)

### Story 3.4: Session Lifecycle Controls

As an Instructor,
I want to transition a session through draft → scheduled → active → closed,
So that I control when QR display and check-in are open.

**Acceptance Criteria:**

**Given** an Instructor on session detail with a bound roster and configured geofence
**When** they advance lifecycle states using the session lifecycle stepper (UX-DR11)
**Then** valid transitions are **draft** → **scheduled** → **active** → **closed** (FR9)
**When** session is **draft**
**Then** a yellow banner reads "Chưa sẵn sàng — cần gắn danh sách và vùng GPS." (UX-DR31)
**When** session is **active**
**Then** QR Display and check-in acceptance are enabled (FR9, FR10)
**When** session is **closed**
**Then** new check-ins are rejected; existing Attendance Records are read-only except via manual override (FR9)
**And** only **active** state enables the QR Display entry point

### Story 3.5: QR Display with Rotating Session Token

As an Instructor,
I want a full-screen QR display that rotates every 30 seconds with a visible countdown,
So that students can scan a valid token during the live workshop.

**Acceptance Criteria:**

**Given** migrations for `session_tokens` table and an **active** workshop session
**When** the Instructor opens QR Display (`app/(instructor)/sessions/[id]/display/`)
**Then** `mintSessionToken(sessionId)` runs in NestJS API only with `expires_at = now() + 30s` (FR10, AD-4)
**And** the QR encodes a URL to the student check-in route with session context
**And** the display polls `GET {NEXT_PUBLIC_API_URL}/api/v1/sessions/:id/qr-token` every ≤5s for the current valid token (AD-4)
**And** the UI shows session title, QR in the display frame, and a visible countdown using qr-countdown typography (UX-DR7, UX-DR13, UX-DR24, UX-DR28)
**When** 30 seconds elapse
**Then** a new token is minted and the QR refreshes; multiple students may use the same token before expiry (FR10)
**When** the Instructor presses ESC
**Then** they return to session detail (UX-DR13)
**And** browser full-screen (F11) works for projector mode with no hover-only controls (UX-DR24)
**And** `prefers-reduced-motion` disables animation on token swap (UX-DR25)
