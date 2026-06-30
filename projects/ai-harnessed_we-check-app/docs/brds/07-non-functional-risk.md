# We Check — Non-functional Requirements and Risks

Measurable quality attributes (`NFR-xx`) and operational risks for **We Check** MVP. Non-functional requirements support business objectives in [00-project-overview.md](./00-project-overview.md) (OBJ-01–OBJ-03, SM-01–SM-04) and enforce constraints from [prompt.md](./prompt.md).

**Related documents:** [Functional requirements](./03-functional-requirements.md) · [Business rules](./04-business-rules.md) · [Acceptance criteria](./08-acceptance-mvp-future.md) · [Stakeholders and scope](./01-stakeholders-scope.md)

---

## 1. Non-functional Requirements Overview

| Category | NFR IDs | Primary trace |
| --- | --- | --- |
| Availability and reliability | NFR-01 – NFR-03 | SM-02, OBJ-01 |
| Performance and scalability | NFR-04 – NFR-08 | OBJ-01, OBJ-03, [FR-06](./03-functional-requirements.md) |
| Security and privacy | NFR-09 – NFR-16 | SM-03, SM-04, [BR-06](./04-business-rules.md) |
| Usability and accessibility | NFR-17 – NFR-20 | [FR-07](./03-functional-requirements.md), locale `vi-VN` |
| Device API fidelity | NFR-24 | [FR-07](./03-functional-requirements.md), [FR-08](./03-functional-requirements.md) |
| Maintainability and operability | NFR-21 – NFR-23 | `ITOperations` stakeholder |

Functional behavior is specified in `FR-xx`; testable acceptance scenarios are in `AC-xx` in [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).

---

## 2. Non-functional Requirements

### 2.1 Availability and reliability

#### NFR-01 — Zero unplanned downtime during live check-in

| Field | Specification |
| --- | --- |
| **Attribute** | Availability |
| **Measure** | Unplanned service interruption during any session in `Active` state with enrolled students |
| **Target** | **0 minutes** unplanned downtime per live session ([SM-02](./00-project-overview.md)) |
| **Verification** | Uptime monitoring during pilot workshops; incident post-mortem if check-in window affected |
| **Traceability** | OBJ-01, SM-02; [FR-05](./03-functional-requirements.md), [FR-06](./03-functional-requirements.md) |

#### NFR-02 — Check-in transaction consistency

| Field | Specification |
| --- | --- |
| **Attribute** | Reliability / data integrity |
| **Measure** | Successful check-in commits exactly one `Present` record per student per session; QR token marked `Consumed` atomically |
| **Target** | **100%** of concurrent check-in attempts produce correct final state under load test (no double `Present`, no lost success) |
| **Verification** | Integration tests with parallel submissions; load test with 150 concurrent check-ins |
| **Traceability** | [FR-09](./03-functional-requirements.md), [BR-04](./04-business-rules.md), [BR-11](./04-business-rules.md) |

#### NFR-03 — Backup and recovery

| Field | Specification |
| --- | --- |
| **Attribute** | Recoverability |
| **Measure** | Attendance records, audit logs, and session metadata restorable after infrastructure failure |
| **Target** | Recovery point objective (RPO) ≤ **24 hours**; recovery time objective (RTO) ≤ **4 hours** for MVP pilot |
| **Verification** | Documented backup schedule; quarterly restore drill for IT Operations |
| **Traceability** | [FR-11](./03-functional-requirements.md), [FR-12](./03-functional-requirements.md); `ITOperations` runbooks |

---

### 2.2 Performance and scalability

#### NFR-04 — Check-in API response time

| Field | Specification |
| --- | --- |
| **Attribute** | Latency |
| **Measure** | Server response time for check-in submission endpoint (p95) under normal pilot network |
| **Target** | p95 ≤ **2 seconds**; student confirmation UI within **2 seconds** under normal conditions ([FR-07](./03-functional-requirements.md)) |
| **Verification** | Load test with 150 concurrent users; APM p95 metrics during pilot |
| **Traceability** | [FR-07](./03-functional-requirements.md), [AC-07](./08-acceptance-mvp-future.md) |

#### NFR-05 — Cohort check-in completion time

| Field | Specification |
| --- | --- |
| **Attribute** | Throughput / workflow duration |
| **Measure** | Elapsed time from session `Active` until **99%** of present enrolled students reach `Present` |
| **Target** | ≤ **5 minutes** for cohorts of **100–150** participants ([OBJ-01](./00-project-overview.md)) |
| **Verification** | Timed pilot sessions; synthetic load test simulating staggered scans |
| **Traceability** | OBJ-01; [product metadata](../product-meta.json) `mvpScale.checkInTimeTargetMinutes` |

#### NFR-06 — QR token refresh cadence

| Field | Specification |
| --- | --- |
| **Attribute** | Timeliness |
| **Measure** | Interval between successive QR token issuances; instructor display countdown accuracy |
| **Target** | New token every **30 seconds** ± **1 second**; expired tokens rejected per [BR-03](./04-business-rules.md) |
| **Verification** | Automated test of token issue timestamps; manual projector display check |
| **Traceability** | [FR-06](./03-functional-requirements.md), [BR-03](./04-business-rules.md), [AC-06](./08-acceptance-mvp-future.md) |

#### NFR-07 — Report availability after session close

| Field | Specification |
| --- | --- |
| **Attribute** | Latency |
| **Measure** | Time from session `Closed` until instructor can view complete session report |
| **Target** | ≤ **10 minutes** ([OBJ-03](./00-project-overview.md)) |
| **Verification** | Timed report access after pilot session close |
| **Traceability** | [FR-12](./03-functional-requirements.md), OBJ-03 |

#### NFR-08 — Live attendance dashboard refresh (Should)

| Field | Specification |
| --- | --- |
| **Attribute** | Near real-time UI |
| **Measure** | Delay between successful student check-in and updated count on instructor dashboard |
| **Target** | ≤ **5 seconds** without manual page reload ([FR-15](./03-functional-requirements.md)) |
| **Verification** | E2E timing during active session with Should-capability enabled |
| **Traceability** | [FR-15](./03-functional-requirements.md), [AC-15](./08-acceptance-mvp-future.md) |

---

### 2.3 Security and privacy

#### NFR-09 — Transport encryption

| Field | Specification |
| --- | --- |
| **Attribute** | Confidentiality in transit |
| **Measure** | All client–server and service-to-service HTTP traffic |
| **Target** | **TLS 1.2+** only; HSTS enabled in production |
| **Verification** | SSL Labs or equivalent scan; reject plain HTTP in production |
| **Traceability** | SM-04; institutional IT security baseline |

#### NFR-10 — Authentication on protected operations

| Field | Specification |
| --- | --- |
| **Attribute** | Authentication |
| **Measure** | Check-in, reporting, export, and admin endpoints |
| **Target** | **100%** of protected operations reject unauthenticated requests ([BR-06](./04-business-rules.md)) |
| **Verification** | Automated API tests without session token; [AC-02](./08-acceptance-mvp-future.md) |
| **Traceability** | [FR-02](./03-functional-requirements.md), [BR-06](./04-business-rules.md) |

#### NFR-11 — Role-based authorization

| Field | Specification |
| --- | --- |
| **Attribute** | Authorization |
| **Measure** | Access to reports, CSV export (including instructor assignment boundary), manual edits, and cross-class data |
| **Target** | **100%** of out-of-scope access attempts denied with audit log ([BR-08](./04-business-rules.md), [BR-09](./04-business-rules.md)). Instructor CSV export limited to assigned class-subject pairs; student export always denied. **UI nav negative matrix:** per role, DOM contains zero links to forbidden route prefixes (`/admin/*` for non-admin, etc.) per [BR-14](./04-business-rules.md) |
| **Verification** | RBAC negative test matrix per role; UI nav audit per [AC-18](./08-acceptance-mvp-future.md); [AC-12](./08-acceptance-mvp-future.md), [AC-13](./08-acceptance-mvp-future.md) |
| **Traceability** | [FR-12](./03-functional-requirements.md), [FR-13](./03-functional-requirements.md), [FR-18](./03-functional-requirements.md) |

#### NFR-12 — GPS data minimization

| Field | Specification |
| --- | --- |
| **Attribute** | Privacy / data minimization |
| **Measure** | Storage of raw device latitude/longitude after check-in validation |
| **Target** | Raw coordinates **not persisted** after successful radius check; only derived outcome (`Present`, distance for audit) and check-in timestamp retained ([FR-08](./03-functional-requirements.md), [BR-02](./04-business-rules.md)) |
| **Verification** | Database schema review; integration test confirming no coordinate columns populated post-success |
| **Traceability** | SM-04; [FR-08](./03-functional-requirements.md), [BR-12](./04-business-rules.md) |

#### NFR-13 — Vietnam personal data protection baseline

| Field | Specification |
| --- | --- |
| **Attribute** | Legal / regulatory compliance |
| **Measure** | Consent capture, purpose limitation, data subject rights, primary data residency |
| **Target** | Pass internal **NĐ 13/2023** checklist before go-live: explicit GPS purpose consent, privacy notice in Vietnamese, data deletion request process, primary application and database hosted in **Vietnam** |
| **Verification** | Legal/compliance sign-off checklist; hosting provider confirmation |
| **Traceability** | SM-04; [01-stakeholders-scope.md](./01-stakeholders-scope.md) constraints |

#### NFR-14 — Credential storage

| Field | Specification |
| --- | --- |
| **Attribute** | Authentication security |
| **Measure** | Password and credential storage |
| **Target** | Passwords hashed with **bcrypt** or **argon2**; no plaintext storage; minimum password length **8** characters for MVP local accounts |
| **Verification** | Code review of auth module; penetration test sample |
| **Traceability** | [FR-02](./03-functional-requirements.md) |

#### NFR-15 — Audit logging for sensitive actions

| Field | Specification |
| --- | --- |
| **Attribute** | Accountability |
| **Measure** | Manual attendance edits, CSV exports, denied export attempts, token reuse alerts, spoof flags |
| **Target** | **100%** of listed actions produce append-only audit records with actor ID, timestamp, and action detail |
| **Verification** | Integration tests for [FR-11](./03-functional-requirements.md), [FR-13](./03-functional-requirements.md), [BR-11](./04-business-rules.md) |
| **Traceability** | [FR-10](./03-functional-requirements.md), [FR-11](./03-functional-requirements.md), [FR-13](./03-functional-requirements.md) |

#### NFR-16 — Session inactivity timeout

| Field | Specification |
| --- | --- |
| **Attribute** | Session management |
| **Measure** | Authenticated web session lifetime without activity |
| **Target** | Expire after **8 hours** of inactivity (configurable by admin within 4–12 hour range) |
| **Verification** | Automated session expiry test |
| **Traceability** | [FR-02](./03-functional-requirements.md) |

---

### 2.4 Usability and accessibility

#### NFR-17 — Vietnamese user interface

| Field | Specification |
| --- | --- |
| **Attribute** | Localization |
| **Measure** | User-facing labels, errors, and notifications |
| **Target** | **100%** of student and instructor UI copy in Vietnamese (`vi-VN`); technical identifiers and docs may use English |
| **Verification** | UI copy review checklist; spot-check error messages in [04-business-rules.md](./04-business-rules.md) |
| **Traceability** | [prompt.md](./prompt.md) §5.3; [product metadata](../product-meta.json) `locale` |

#### NFR-18 — Mobile web platform support

| Field | Specification |
| --- | --- |
| **Attribute** | Compatibility |
| **Measure** | Student check-in flow on reference devices |
| **Target** | Functional QR scan and GPS on **iOS 15+ Safari** and **Android 10+ Chrome** without native app install |
| **Verification** | Device matrix test on ≥ **4** physical devices before pilot |
| **Traceability** | [FR-07](./03-functional-requirements.md), [FR-08](./03-functional-requirements.md) |

#### NFR-19 — Permission-denied recovery guidance

| Field | Specification |
| --- | --- |
| **Attribute** | Usability |
| **Measure** | Camera and GPS permission denial flows |
| **Target** | Clear Vietnamese instructions with platform-specific steps when camera or GPS unavailable; link to help content; instructor manual fallback documented in UI |
| **Verification** | UX walkthrough on iOS and Android with permissions denied |
| **Traceability** | [BR-12](./04-business-rules.md); [FR-11](./03-functional-requirements.md) fallback |

#### NFR-20 — Projector-readable QR display

| Field | Specification |
| --- | --- |
| **Attribute** | Visual clarity |
| **Measure** | Instructor QR display at typical classroom projection distance |
| **Target** | QR scannable from **5 m** at **1280×720** minimum projection; countdown timer visible; minimum contrast ratio **4.5:1** for timer text |
| **Verification** | Field test in ≥ **2** pilot classrooms |
| **Traceability** | [FR-06](./03-functional-requirements.md); UI/UX specs under `docs/ui-ux/` |

#### NFR-24 — Device API fidelity

| Field | Specification |
| --- | --- |
| **Attribute** | Client device API behavior |
| **Measure** | Camera and GPS acquisition paths in production vs test/demo builds |
| **Target** | **Production builds:** `VITE_ENABLE_DEVICE_SIMULATION` **off**; URL params (`gpsSim`, `cameraSim`, `gpsLat`/`gpsLng`) **ignored** with optional dev-console warning. **Test/demo builds:** flag **on** → query-param simulation layer in [demo-guides.md](../demo-guides.md) §7 remains valid. E2E harness sets flag on in Playwright config ([11-testing-plan.md](../technical/11-testing-plan.md)) |
| **Verification** | Integration contract with sim off; E2E with sim on; [AC-08e](./08-acceptance-mvp-future.md) |
| **Traceability** | [FR-07](./03-functional-requirements.md), [FR-08](./03-functional-requirements.md) |

---

### 2.5 Maintainability and operability

#### NFR-21 — Structured operational logging

| Field | Specification |
| --- | --- |
| **Attribute** | Observability |
| **Measure** | Application and API request logs |
| **Target** | JSON or structured logs with correlation ID, timestamp, endpoint, outcome code, and session ID where applicable; no passwords or raw GPS in logs |
| **Verification** | Log sample review during load test |
| **Traceability** | `ITOperations` stakeholder; incident response |

#### NFR-22 — Health check endpoints

| Field | Specification |
| --- | --- |
| **Attribute** | Operability |
| **Measure** | Liveness and readiness probes |
| **Target** | HTTP health endpoints return **200** when database and core services reachable; used by hosting monitor |
| **Verification** | Deploy checklist; simulate dependency failure |
| **Traceability** | `ITOperations` runbooks |

#### NFR-23 — Pre-pilot load test baseline

| Field | Specification |
| --- | --- |
| **Attribute** | Scalability |
| **Measure** | Concurrent users during simulated check-in peak |
| **Target** | System sustains **500** concurrent users with check-in p95 ≤ **3 seconds** and error rate < **0.1%** before production pilot |
| **Verification** | Documented load test report; remediation plan if targets missed |
| **Traceability** | Risk R-04 mitigation; multi-class simultaneous check-in scenario |

---

## 3. Risks

| Risk ID | Description | Likelihood | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- | --- |
| R-01 | Student lacks smartphone, dead battery, or unstable network during check-in | Medium | High — false `Absent`, increased complaints | Instructor manual attendance ([FR-11](./03-functional-requirements.md)); pre-session policy on chargers; client retry up to **3** attempts within **30 seconds** on network failure | Instructor, Training Office |
| R-02 | GPS spoofing via fake-location apps bypasses radius check | High | High — undermines core anti-fraud value | [FR-10](./03-functional-requirements.md) mock-location signals; abnormal accuracy heuristics; instructor override after physical verify; audit log | Engineering, Instructor |
| R-03 | QR code shared within 30-second window for proxy check-in | High | High — attendance integrity loss | One-time-use token ([BR-11](./04-business-rules.md)); one check-in per account ([BR-04](./04-business-rules.md)); security alert on token reuse | Engineering |
| R-04 | Server overload when multiple classes check in simultaneously | High | High — QR fails to load, check-ins lost | [NFR-23](./07-non-functional-risk.md); horizontal scaling; queue with retry; CDN for static QR assets; CPU/RAM alerts at **80%** | IT Operations |
| R-05 | Personal data breach (identity, attendance history, location metadata) | Medium | Very high — NĐ 13/2023 violation, reputational harm | [NFR-09](./07-non-functional-risk.md)–[NFR-15](./07-non-functional-risk.md); RBAC; encryption at rest (AES-256); data processing agreement before go-live | Training Office, Legal |
| R-06 | Instructor unfamiliar with system blocks session start | Medium | High — entire class cannot check in digitally | Quick-start guide; ≤ **3** step session open flow; pre-pilot training session; on-call support during first workshops | Training Office |
| R-07 | Students deny camera or GPS browser permissions | Medium | Medium — cannot complete automated check-in | [NFR-19](./07-non-functional-risk.md); permission onboarding copy; manual fallback ([BR-10](./04-business-rules.md)) | Engineering, Instructor |
| R-08 | Shared or stolen student credentials enable remote proxy check-in | Medium | High — identity verification weakened | Mandatory auth before check-in; session timeout ([NFR-16](./07-non-functional-risk.md)); GPS still required; future SSO/2FA | Training Office |
| R-09 | Academic roster API unavailable at pilot start | High | Medium — delayed rollout, manual CSV import burden | [FR-03](./03-functional-requirements.md) CSV import path; confirm data format with IT before sprint 1 | Training Office, IT Operations |
| R-10 | Default **100 m** GPS radius unsuitable for specific rooms | High | Medium — false rejections or undetected fraud | Instructor-adjustable radius per session ([FR-04](./03-functional-requirements.md)); field calibration at ≥ **3** room sizes before scaling pilot | Instructor, Engineering |

---

## 4. Open issues

| Issue ID | Description | Likelihood | Impact | Resolution path | Status |
| --- | --- | --- | --- | --- | --- |
| I-01 | Data controller vs. processor role under NĐ 13/2023 not formally assigned | Medium | High | Legal review with training office before week 4 of pilot | Open |
| I-02 | Authentication method (campus SSO vs. standalone email/password) not finalized | High | Medium | Confirm with IT Operations before sprint 1; MVP defaults to email/password per [FR-02](./03-functional-requirements.md) | Open |
| I-03 | Hosting provider and Vietnam data residency contract pending | Medium | High | Select VN cloud provider (e.g., VNG Cloud, FPT Cloud) before infrastructure design lock | Open |

---

## 5. Risk monitoring

| Metric | Target / alert threshold | Review cadence |
| --- | --- | --- |
| Check-in success rate (present attendees) | ≥ **99%** ([SM-01](./00-project-overview.md)); alert if < **95%** in any session | Per session during pilot |
| Check-in API error rate | < **0.5%** during active window | Real-time dashboard |
| GPS / permission rejection rate | Track `GpsDisabled` and `OutOfRadius` counts | Weekly during pilot |
| Spoof and token-reuse incidents | Log count and instructor override rate | Weekly |
| Session downtime during `Active` | **0** minutes | Per session |
| Report generation latency | ≤ **10 minutes** | Per session |

Post-pilot retrospective: review R-01–R-10 occurrence, adjust GPS defaults, and update [04-business-rules.md](./04-business-rules.md) if policy changes.

---

## 6. NFR traceability matrix

| NFR ID | Related FR | Related BR | Success metric |
| --- | --- | --- | --- |
| NFR-01 | FR-05, FR-06 | — | SM-02 |
| NFR-02 | FR-09 | BR-04, BR-11 | SM-01 |
| NFR-04, NFR-05 | FR-07 | — | OBJ-01 |
| NFR-06 | FR-06 | BR-03 | — |
| NFR-07 | FR-12 | — | OBJ-03 |
| NFR-10 | FR-02 | BR-06 | — |
| NFR-11 | FR-12, FR-13, FR-18 | BR-08, BR-09, BR-14 | — |
| NFR-24 | FR-07, FR-08 | — | — |
| NFR-12 | FR-08 | BR-02, BR-12 | SM-04 |
| NFR-13 | — | — | SM-04 |

---

## 7. Future consideration

| Enhancement | Affected NFR area |
| --- | --- |
| SSO / campus identity provider | NFR-10, NFR-14, NFR-16 |
| Two-factor authentication | NFR-10, risk R-08 |
| WiFi BSSID indoor verification | NFR-12, risk R-02 |
| Auto-scaling beyond 500 concurrent users | NFR-23 |
| Long-term GPS retention policy | NFR-12, NFR-13 |
| PIN-based fallback when device unavailable | Risk R-01 mitigation |
| WCAG 2.1 AA formal audit | NFR-17, NFR-19 |
| Offline check-in queue | NFR-01, NFR-04 |
