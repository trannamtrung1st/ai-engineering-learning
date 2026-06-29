# We Check — Acceptance Criteria and MVP / Future Scope

Testable acceptance criteria (`AC-xx`) for **We Check** MVP. Each criterion uses Given / When / Then format and traces to functional requirements (`FR-xx`) and business rules (`BR-xx`). Non-functional targets are in [07-non-functional-risk.md](./07-non-functional-risk.md).

**Related documents:** [Functional requirements](./03-functional-requirements.md) · [Business rules](./04-business-rules.md) · [Business workflow](./02-business-workflow.md) · [MVP prompt](./prompt.md) · [Stakeholders and scope](./01-stakeholders-scope.md)

---

## 1. Acceptance Criteria Overview

| ID range | Capability area | MVP priority | Primary FR |
| --- | --- | --- | --- |
| AC-01 – AC-03 | Identity, auth, roster | Must | FR-01 – FR-03 |
| AC-04 – AC-06 | Session lifecycle and QR | Must | FR-04 – FR-06 |
| AC-07 – AC-10 | Mobile check-in, GPS, anti-fraud | Must | FR-07 – FR-10 |
| AC-11 – AC-14 | Manual edits, reporting, export, student history | Must | FR-11 – FR-14 |
| AC-15 – AC-16 | Dashboard and absence warnings | Should | FR-15 – FR-16 |
| AC-17 – AC-18 | Bootstrap, nav permissions, role hubs | Must | FR-17 – FR-18 |

---

## 2. Must — Identity, Authentication, and Roster

### AC-01 — User account provisioning

**Traces:** [FR-01](./03-functional-requirements.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-01a | A `TrainingOfficeAdmin` with valid admin session | Admin creates a student account with unique student ID, display name, email, and role `Student` | Account is persisted with `active=true`; student can authenticate |
| AC-01b | A student ID already exists in the system | Admin attempts to create another account with the same student ID | Request is rejected with a validation error; no duplicate record created |
| AC-01c | A user account with `active=false` | Deactivated user attempts login | Login fails with localized error; check-in is not permitted |

### AC-02 — Authentication before check-in

**Traces:** [FR-02](./03-functional-requirements.md), [BR-06](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-02a | An unauthenticated student opens a check-in deep link from a scanned QR | Browser loads the check-in route | User is redirected to login; no attendance record is created; outcome `Unauthenticated` if API invoked directly |
| AC-02b | A student completes login after redirect from check-in URL | Credentials are valid | User returns to the check-in flow with session established |
| AC-02c | An authenticated session idle for more than **8 hours** | Student submits check-in | Session is expired; user must re-authenticate before check-in succeeds |

### AC-03 — Roster import and maintenance

**Traces:** [FR-03](./03-functional-requirements.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-03a | A CSV with required columns (student ID, full name, class code, subject code) and valid rows | `TrainingOfficeAdmin` imports the file | Enrollments are created; import summary shows accepted and rejected row counts |
| AC-03b | A CSV containing a duplicate student ID within the same class | Admin imports the file | Duplicate rows are rejected with row-level errors; valid rows still import; no silent partial failure |
| AC-03c | An `Instructor` assigned to class `HESD-01` | Instructor views roster for an unassigned class | Access is denied; no roster data returned |
| AC-03d | Admin with `roster:write` | Admin creates class `HESD-03` and subject `SWE-102` via `/admin/classes/new` | Records persisted; appear in roster filters and import validation |
| AC-03e | Class code `HESD-03` already exists | Admin attempts duplicate class code | Request rejected with localized validation error |

---

### AC-17 — Initial admin bootstrap

**Traces:** [FR-17](./03-functional-requirements.md), [BR-13](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-17a | Empty database (`User.count = 0`) | Visitor opens `/` | Redirected to `/setup`; login link hidden or disabled |
| AC-17b | Valid setup form on `/setup` | Admin submits institutional ID, name, email, password | First `TrainingOfficeAdmin` created; session established; lands on `/admin` hub |
| AC-17c | Setup already complete (`needsSetup: false`) | Visitor opens `/setup` or repeats `POST /setup/first-admin` | `/setup` returns 403 or redirects to login; repeat POST rejected with `SetupAlreadyComplete` |
| AC-17d | Duplicate email or institutional ID on setup form | Admin submits | Field validation error; no user created |

### AC-18 — Permission-gated navigation and role home hubs

**Traces:** [FR-18](./03-functional-requirements.md), [BR-14](./04-business-rules.md), [NFR-11](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-18a | Logged-in `Instructor` | User views layout chrome | Sidebar shows only instructor items; zero admin nav entries anywhere in chrome |
| AC-18b | Logged-in `Student` | Student navigates to `/admin/users` via URL | `ForbiddenPage` shown; student chrome never displayed admin links |
| AC-18c | Logged-in `TrainingOfficeAdmin` | Admin lands on `/admin` hub | All permitted workflow cards visible with working deep links |
| AC-18d | Logged-in `Instructor` with `report:read` | Instructor lands on `/sessions` | Hub section shows **Tạo buổi học mới** and **Báo cáo** links |
| AC-18e | Authenticated user of any role | User visits `/` | Redirect to role home hub per role table in [FR-18](./03-functional-requirements.md) |

---

## 3. Must — Session Lifecycle and QR Display

### AC-04 — Session creation with room GPS

**Traces:** [FR-04](./03-functional-requirements.md), [BR-07](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-04a | An authenticated `Instructor` | Instructor creates a session with class, subject, schedule, room name, latitude, longitude, and default **100 m** radius | Session is saved in `Draft` state with configured GPS |
| AC-04b | A `Draft` session missing valid room coordinates | Instructor requests open (`Draft` → `Active`) | Transition is blocked; UI message requires room GPS configuration |
| AC-04c | A `Draft` session the instructor no longer needs | Instructor cancels the session | Session transitions to `Cancelled` (terminal) |

### AC-05 — Open, monitor, and close live session

**Traces:** [FR-05](./03-functional-requirements.md), [BR-01](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-05a | A `Draft` session with valid room GPS | Instructor opens the session | Session becomes `Active`; attendance window starts; QR issuance begins |
| AC-05b | An `Active` session and current time ≤ `scheduledStartTime` + **10 minutes** | Enrolled student submits valid check-in | Check-in is evaluated per [BR interaction matrix](./04-business-rules.md#7-rule-interaction-matrix) |
| AC-05c | An `Active` session and current time > `scheduledStartTime` + **10 minutes** without manual close | System scheduler runs | Session auto-transitions to `Closed`; all `Pending` records become `Absent` |
| AC-05d | A student with `Pending` status after session is `Closed` | Student attempts check-in | Outcome `SessionNotActive`; status remains `Absent` unless instructor manually overrides ([BR-10](./04-business-rules.md)) |

### AC-06 — Rotating dynamic QR display

**Traces:** [FR-06](./03-functional-requirements.md), [BR-03](./04-business-rules.md), [NFR-06](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-06a | A session in `Active` state | Instructor views QR display | QR image refreshes automatically every **30 seconds** with visible countdown |
| AC-06b | A QR token issued at time T | Student scans at T + **31 seconds** | Check-in rejected with outcome `ExpiredQr` and Vietnamese message: *Mã QR đã hết hạn, vui lòng quét mã mới* |
| AC-06c | Session is not `Active` | Instructor or student requests current QR token | No valid token issued; display shows session-not-active state |

---

## 4. Must — Check-In, GPS, and Anti-Fraud

### AC-07 — Mobile web QR scan check-in success

**Traces:** [FR-07](./03-functional-requirements.md), [BR-15](./04-business-rules.md), [NFR-04](./07-non-functional-risk.md), [NFR-18](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-07a | An authenticated enrolled student, session `Active`, valid unexpired QR token, GPS within radius | Student scans QR, preflight passes, and submits check-in from mobile browser (iOS Safari or Android Chrome) | Attendance becomes `Present`; confirmation shown within **2 seconds** under normal network; token becomes `Consumed` |
| AC-07b | A student not enrolled in the session | Student preflight or submit for that session | Check-in rejected; no `Present` record created; outcome *Bạn không thuộc danh sách lớp của buổi học này* |
| AC-07c | Enrolled student, session `Active`, valid token | Student scans QR → preflight **200** | Flow advances to GPS step with session summary (class, subject, room) visible |
| AC-07d | Expired or unknown token | Student scans → preflight rejects | User remains on scan step or `ExpiredQr` outcome; `GpsCaptureStep` never mounts |
| AC-07e | `studentb` not enrolled in session class-subject | Student scans valid token for that session | Preflight returns `NotEnrolled`; outcome shown without GPS step |
| AC-07f | QR payload `session` id mismatches token's bound session | Student scans → preflight | Rejected with `TokenNotFound` or `SessionMismatch`; GPS step never mounts |

### AC-08 — GPS location verification

**Traces:** [FR-08](./03-functional-requirements.md), [BR-02](./04-business-rules.md), [BR-12](./04-business-rules.md), [NFR-12](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-08a | Device coordinates within **100 m** (or session override radius) of room point | Student submits check-in | Radius check passes; flow continues to success if all other rules pass |
| AC-08b | Device coordinates outside configured radius | Student submits check-in | Outcome `OutOfRadius`; attendance not set to `Present` |
| AC-08c | GPS disabled or browser location permission denied (or client timeout after **15 seconds**) | Student initiates check-in | Outcome `GpsDisabled`; Vietnamese message: *Vui lòng bật GPS và cấp quyền định vị để điểm danh* with help link |
| AC-08d | A successful check-in completing radius validation | Server persists attendance outcome | Raw latitude/longitude are **not** stored in long-term attendance tables |
| AC-08e | Simulation disabled (`VITE_ENABLE_DEVICE_SIMULATION=false`) | Student check-in | Client uses browser `geolocation` API; URL sim params ignored. With simulation enabled, `gpsSim=delay` resolves without real GPS permission |
| AC-08f | Device coordinates acquired in-radius (`gpsState === "ready"`) | GPS step renders | *Vị trí đã sẵn sàng* shown **without** spinner; `aria-busy` absent; **Xác nhận điểm danh** enabled immediately |
| AC-08g | Student taps **Xác nhận điểm danh** | Submit in flight (`submitting`) | Spinner returns; submit disabled until API outcome |

### AC-09 — Anti-proxy and duplicate check-in prevention

**Traces:** [FR-09](./03-functional-requirements.md), [BR-04](./04-business-rules.md), [BR-11](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-09a | Student already has `Present` for the session | Same student submits another check-in | HTTP **409** semantics; outcome `DuplicateCheckIn`; message: *Bạn đã điểm danh buổi học này rồi* |
| AC-09b | A QR token already `Consumed` by another student within the 30-second window | A second student submits the same token | Check-in rejected; security log entry with session ID, token ID, and submitting student ID |
| AC-09c | Two parallel check-in requests from the same student for the same session | Both arrive nearly simultaneously | Exactly one succeeds as `Present`; the other receives `DuplicateCheckIn` |

### AC-10 — Anti-GPS-spoofing baseline

**Traces:** [FR-10](./03-functional-requirements.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-10a | Device reports mock-location indicator (Android) or abnormally perfect accuracy per baseline heuristic | Student submits check-in | Outcome `SpoofSuspected`; check-in rejected pending review |
| AC-10b | Student check-in flagged `SpoofSuspected` and instructor physically verifies presence | Instructor manually sets status to `Present` with note | Record updated; audit log captures override |
| AC-10c | Any spoof-suspected or token-reuse event | Event occurs | Append-only security audit entry created |

---

## 5. Must — Corrections, Reporting, and Export

### AC-11 — Instructor manual attendance edit

**Traces:** [FR-11](./03-functional-requirements.md), [BR-10](./04-business-rules.md), [NFR-15](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-11a | Session `Closed` within **24 hours** of `closedAt` | Assigned instructor changes student status from `Absent` to `Present` with optional note | Status updated; audit record includes editor ID, timestamp, previous and new status |
| AC-11b | Session `Closed` more than **24 hours** ago | Instructor attempts edit | Edit blocked for instructor role |
| AC-11c | Session `Closed` more than **24 hours** ago | `TrainingOfficeAdmin` edits attendance | Edit succeeds with audit log |

### AC-12 — Attendance reporting by class and subject

**Traces:** [FR-12](./03-functional-requirements.md), [BR-08](./04-business-rules.md), [NFR-07](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-12a | Instructor assigned to class `HESD-01` / subject `SWE-101` | Instructor opens attendance report for that class and subject | Tabular roster with statuses and summary counts (present, absent, excused) is returned |
| AC-12b | Instructor **not** assigned to requested class | Instructor opens report | Access denied with localized permission error |
| AC-12c | `TrainingOfficeAdmin` | Admin opens institution-wide report with date filter | All cohorts visible within filter; report available within **10 minutes** of session close |

### AC-13 — CSV export for training office

**Traces:** [FR-13](./03-functional-requirements.md), [BR-09](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-13a | `TrainingOfficeAdmin` viewing a filtered report | Admin requests CSV export | CSV downloads with columns: student ID, name, class, subject, session date, attendance status, check-in timestamp (when present); export action audit-logged |
| AC-13b | `Instructor` or `Student` | User requests CSV export | Export rejected; message: *Chỉ phòng đào tạo mới có quyền xuất dữ liệu*; denied attempt logged |

### AC-14 — Student personal attendance history

**Traces:** [FR-14](./03-functional-requirements.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-14a | Authenticated `Student` with enrollment history | Student opens personal attendance history | Paginated list shows only own records: session date, subject, status, check-in time when applicable |
| AC-14b | Authenticated `Student` | Student attempts to access another student's record via API | Request returns **403** or empty scoped result; no peer data exposed |

---

## 6. Should — Enhancements

### AC-15 — Real-time attendance dashboard

**Traces:** [FR-15](./03-functional-requirements.md), [NFR-08](./07-non-functional-risk.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-15a | Session `Active` and Should-capability enabled | Instructor views session monitor | Live count of `Present` vs total enrolled updates within **5 seconds** of each successful check-in without manual reload |
| AC-15b | Session `Active` | Instructor sorts roster grid by status | Sort order reflects current attendance states accurately |

### AC-16 — Automatic absence threshold warning

**Traces:** [FR-16](./03-functional-requirements.md), [BR-05](./04-business-rules.md)

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-16a | Student has unexcused `Absent` count > **20%** of completed sessions in a subject (excluding `Excused`) | Session transitions to `Closed` and rates recalculate | In-app notification sent to student and assigned instructor |
| AC-16b | Student absence includes `Excused` records | Rate is calculated | `Excused` absences excluded from numerator |

---

## 7. MVP scope

The following capabilities are **in scope** for the We Check MVP pilot with HESD cohorts (100–150 participants per session).

### 7.1 Must (release blockers)

| Capability | FR | Validated by |
| --- | --- | --- |
| User provisioning and deactivation | FR-01 | AC-01 |
| Email/password authentication | FR-02 | AC-02 |
| CSV roster import | FR-03 | AC-03 |
| Manual class and subject creation | FR-03 | AC-03d, AC-03e |
| First admin bootstrap (`/setup`) | FR-17 | AC-17 |
| Permission-gated nav and role home hubs | FR-18 | AC-18 |
| QR preflight gate before GPS | FR-07 | AC-07c–AC-07f |
| GPS ready-state UX (no spinner when ready) | FR-08 | AC-08f, AC-08g |
| Device API fidelity (sim flag) | FR-07, FR-08 | AC-08e, NFR-24 |
| Session creation with room GPS (default **100 m** radius) | FR-04 | AC-04 |
| Open/close session with **10-minute** attendance window | FR-05 | AC-05 |
| Rotating QR (**30 s** token) | FR-06 | AC-06 |
| Mobile web QR scan (no native app) | FR-07 | AC-07 |
| GPS radius verification; permission required | FR-08 | AC-08 |
| One check-in per student; one-time QR token | FR-09 | AC-09 |
| GPS spoofing baseline detection | FR-10 | AC-10 |
| Manual attendance edit with **24 h** instructor window | FR-11 | AC-11 |
| Class/subject reports by assignment | FR-12 | AC-12 |
| CSV export (training office admin only) | FR-13 | AC-13 |
| Student personal attendance history | FR-14 | AC-14 |

### 7.2 Should (include if schedule allows)

| Capability | FR | Validated by |
| --- | --- | --- |
| Real-time instructor attendance dashboard | FR-15 | AC-15 |
| **20%** unexcused absence warning notifications | FR-16 | AC-16 |
| Quick-start onboarding for camera/GPS permissions | [prompt.md](./prompt.md) §2.2 | UX review |

### 7.3 Explicitly out of scope (MVP)

| Excluded item | Rationale |
| --- | --- |
| Facial recognition | [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.2 |
| Tuition payment | Unrelated domain |
| Exam schedule management | Separate academic module |
| Native iOS/Android apps | Mobile web only |
| Offline check-in queue | Network retry only |
| Deep SIS integration | CSV/manual roster for MVP |
| SSO / campus IdP | Email/password auth in MVP |

---

## 8. Future consideration

Enhancements deferred beyond MVP; not required for pilot exit.

| Enhancement | Motivation | Affected FR / AC |
| --- | --- | --- |
| SSO / campus identity provider integration | Reduce credential sharing; align with IT policy | FR-02; risk R-08 in [07-non-functional-risk.md](./07-non-functional-risk.md) |
| Two-factor authentication | Harden high-value accounts | FR-02 |
| WiFi BSSID verification | Improve indoor GPS accuracy | FR-08 |
| PIN-based fallback check-in | Battery-dead device scenario | New FR; risk R-01 |
| Academic API roster sync | Replace manual CSV import | FR-03 |
| Auto-scaling load tests beyond 500 users | Multi-faculty rollout | NFR-23 |
| Long-term GPS retention policies | Compliance beyond verification window | NFR-12, NFR-13 |
| Permission onboarding wizard (first check-in) | Reduce `GpsDisabled` rate | FR-07 UX |
| Configurable QR validity | Not recommended — weakens anti-share controls | BR-03 |
| Device fingerprint on token reuse | Strengthen fraud alerts | BR-11 |

---

## 9. MVP exit indicators

The MVP pilot is considered successful when all of the following are true for at least **one** full HESD workshop cohort:

| Indicator | Target | Evidence |
| --- | --- | --- |
| Cohort check-in duration | ≤ **5 minutes** for 100–150 students | Timed pilot session log |
| Check-in success rate | ≥ **99%** of physically present attendees marked `Present` without manual reconciliation | Session report vs. headcount |
| Identity verification rate | ≥ **98%** automated verification success | [OBJ-02](./00-project-overview.md) |
| Live session stability | **0** unplanned downtime during check-in window | Monitoring / incident log |
| Report readiness | Attendance report and admin CSV within **10 minutes** of close | Timed export |
| Anti-fraud controls | **100%** of duplicate and expired-QR test scenarios pass ([AC-09](./08-acceptance-mvp-future.md), [AC-06b](./08-acceptance-mvp-future.md)) | Pre-go-live test suite |
| Privacy baseline | NĐ 13/2023 internal checklist passed ([NFR-13](./07-non-functional-risk.md)) | Compliance sign-off |
| Organizer adoption | At least one instructor runs end-to-end without paper roll call | Training office confirmation |

---

## 10. Acceptance traceability matrix

| AC ID | FR | BR | NFR |
| --- | --- | --- | --- |
| AC-01 | FR-01 | — | — |
| AC-02 | FR-02 | BR-06 | NFR-10, NFR-16 |
| AC-03 | FR-03 | — | — |
| AC-17 | FR-17 | BR-13 | NFR-16 |
| AC-18 | FR-18 | BR-14 | NFR-11 |
| AC-04 | FR-04 | BR-07 | — |
| AC-05 | FR-05 | BR-01 | NFR-01 |
| AC-06 | FR-06 | BR-03 | NFR-06 |
| AC-07 | FR-07 | BR-03, BR-15 | NFR-04, NFR-18, NFR-24 |
| AC-08 | FR-08 | BR-02, BR-12 | NFR-12, NFR-24 |
| AC-09 | FR-09 | BR-04, BR-11 | NFR-02 |
| AC-10 | FR-10 | — | NFR-15 |
| AC-11 | FR-11 | BR-10 | NFR-15 |
| AC-12 | FR-12 | BR-08 | NFR-07, NFR-11 |
| AC-13 | FR-13 | BR-09 | NFR-11, NFR-15 |
| AC-14 | FR-14 | — | — |
| AC-15 | FR-15 | — | NFR-08 |
| AC-16 | FR-16 | BR-05 | — |
