# We Check — Error Handling

Error taxonomy, response contracts, logging, and client retry policy for **We Check** MVP. Aligns API behavior with [API design](./05-api-design.md) §10 and check-in outcome mapping §6.3. User-facing messages are Vietnamese; stable English `errorCode` values support programmatic handling.

**Related documents:** [Validation rules](./08-validation-rules.md) · [API design](./05-api-design.md) · [Business rules](../brds/04-business-rules.md) · [Non-functional requirements](../brds/07-non-functional-risk.md) · [Main workflows](./06-main-workflows.md)

---

## 1. Error Handling Goals

| Goal | Specification | NFR |
| --- | --- | --- |
| Predictable client semantics | Every failure maps to one HTTP status + one `errorCode` | NFR-10 |
| User-safe messaging | No stack traces, SQL, or internal IDs in responses | NFR-17 |
| Auditability | Sensitive denials and check-in failures logged with correlation ID | NFR-15, NFR-21 |
| Data integrity | Transaction rollback on partial domain failure | NFR-02 |
| Privacy | Raw GPS coordinates never appear in logs or error payloads | NFR-12 |

---

## 2. Error Taxonomy

### 2.1 Client and validation errors (`400`, `422`)

| Category | Examples | Typical errorCode |
| --- | --- | --- |
| Malformed JSON | Unparseable body | `MalformedJson` |
| Schema violation | Missing required field, wrong type | `ValidationFailed` |
| Check-in rejection | Out of radius, expired QR, GPS disabled | `OutOfRadius`, `ExpiredQr`, `GpsDisabled` |
| Spoof detection | Mock location flagged | `SpoofSuspected` |

`400` is used for check-in domain rejections and malformed requests. `422` is used for semantic validation on admin forms (duplicate email, invalid session patch).

### 2.2 Authentication errors (`401`)

| Condition | errorCode | Message (vi-VN example) | BR |
| --- | --- | --- | --- |
| Missing session cookie / bearer token | `Unauthenticated` | *Vui lòng đăng nhập để tiếp tục* | BR-06 |
| Invalid or expired session | `SessionExpired` | *Phiên đăng nhập đã hết hạn* | FR-02 |
| Wrong email or password | `InvalidCredentials` | *Email hoặc mật khẩu không đúng* | FR-02 |
| Deactivated account | `AccountDeactivated` | *Tài khoản đã bị vô hiệu hóa* | FR-01 |

Login failures return `401` for invalid credentials and `403` for deactivated accounts per [05-api-design.md](./05-api-design.md) §2.2.

### 2.3 Authorization errors (`403`)

| Condition | errorCode | BR / FR |
| --- | --- | --- |
| Role lacks permission | `Forbidden` | BR-08, BR-09 |
| Session not `Active` for check-in | `SessionNotActive` | BR-01 |
| Student not enrolled | `NotEnrolled` | FR-03 |
| Instructor edit window expired | `EditWindowExpired` | BR-10 |
| Instructor views out-of-scope roster | `Forbidden` | AC-03c |

### 2.4 Not found (`404`)

| Condition | errorCode | Notes |
| --- | --- | --- |
| Unknown resource ID | `NotFound` | Generic message; no existence leak across scopes |
| Unknown QR token | `TokenNotFound` | Check-in specific |

Out-of-scope resources return `403` or empty list per authorization policy — not `404` — when revealing existence would leak data ([BR-08](../brds/04-business-rules.md)).

### 2.5 Conflict errors (`409`)

| Condition | errorCode | BR |
| --- | --- | --- |
| Duplicate successful check-in | `DuplicateCheckIn` | BR-04 |
| Illegal state transition | `InvalidSessionState` | [07-state-machines.md](./07-state-machines.md) |
| Concurrent attendance update | `Conflict` | Optimistic lock version mismatch |

Message for duplicate check-in: *Bạn đã điểm danh buổi học này rồi* ([AC-09a](../brds/08-acceptance-mvp-future.md)).

### 2.6 Rate limiting (`429`)

| Condition | errorCode | Header |
| --- | --- | --- |
| Too many requests | `RateLimitExceeded` | `Retry-After: <seconds>` |

Limits defined in [05-api-design.md](./05-api-design.md) §10.3 and [08-validation-rules.md](./08-validation-rules.md) §7.

### 2.7 Server errors (`500`, `503`)

| Condition | Client behavior | Internal action |
| --- | --- | --- |
| Unhandled exception | Generic Vietnamese message | Log stack + `requestId` |
| Database unavailable | *Hệ thống tạm thời không khả dụng* | Return `503`; health check fails |
| Transaction deadlock (retryable) | Optional single client retry | Log at warn level |

Never expose exception class names or query text to clients ([NFR-21](../brds/07-non-functional-risk.md)).

---

## 3. Standard Response Envelopes

### 3.1 General API error

Used by all endpoints except check-in success/failure dual shape.

```json
{
  "errorCode": "ValidationFailed",
  "message": "Tọa độ phòng học không hợp lệ",
  "details": [
    {
      "field": "roomLatitude",
      "code": "OutOfRange",
      "message": "Giá trị phải từ -90 đến 90"
    }
  ],
  "requestId": "550e8400-e29b-41d4-a716-446655440000"
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `errorCode` | string | Yes | Stable English identifier |
| `message` | string | Yes | Vietnamese user-facing summary |
| `details` | array | No | Field-level errors for forms |
| `requestId` | UUID | Yes | Correlation ID from middleware |

### 3.2 Check-in response (success and failure)

Check-in uses dedicated shape per [05-api-design.md](./05-api-design.md) §6.2:

**Success (`200`):**

```json
{
  "outcome": "Success",
  "message": "Điểm danh thành công",
  "attendance": {
    "status": "Present",
    "checkedInAt": "2026-06-28T08:05:12.000Z"
  }
}
```

**Failure (`4xx`):**

```json
{
  "outcome": "OutOfRadius",
  "message": "Bạn đang ngoài phạm vi phòng học. Vui lòng di chuyển gần hơn hoặc liên hệ giảng viên.",
  "errorCode": "OutOfRadius"
}
```

Every check-in attempt persists a `CheckInAttempt` row with `outcome` regardless of HTTP status ([FR-09](../brds/03-functional-requirements.md)).

### 3.3 HTTP status summary

| HTTP | Usage |
| --- | --- |
| 400 | Client error, check-in rejection, malformed JSON |
| 401 | Missing or invalid session |
| 403 | Permission denied, session not active, not enrolled |
| 404 | Resource or token not found |
| 409 | Duplicate check-in, invalid state transition |
| 422 | Validation failure on admin writes |
| 429 | Rate limit exceeded |
| 500 | Unexpected server error |
| 503 | Dependency unavailable |

---

## 4. Error Code Catalog (MVP)

Complete stable identifiers for implementation and OpenAPI enum generation.

### 4.1 Authentication and identity

| errorCode | HTTP | Vietnamese message (default) |
| --- | --- | --- |
| `Unauthenticated` | 401 | *Vui lòng đăng nhập để tiếp tục* |
| `SessionExpired` | 401 | *Phiên đăng nhập đã hết hạn* |
| `InvalidCredentials` | 401 | *Email hoặc mật khẩu không đúng* |
| `AccountDeactivated` | 403 | *Tài khoản đã bị vô hiệu hóa* |

### 4.2 Authorization

| errorCode | HTTP | Vietnamese message (default) |
| --- | --- | --- |
| `Forbidden` | 403 | *Bạn không có quyền thực hiện thao tác này* |
| `NotEnrolled` | 403 | *Bạn không thuộc danh sách lớp của buổi học này* |
| `SessionNotActive` | 403 | *Buổi học chưa mở hoặc đã kết thúc* |
| `EditWindowExpired` | 403 | *Đã quá thời hạn chỉnh sửa điểm danh (24 giờ)* |

### 4.3 Validation and input

| errorCode | HTTP | Vietnamese message (default) |
| --- | --- | --- |
| `ValidationFailed` | 422 | *Dữ liệu không hợp lệ* |
| `MalformedJson` | 400 | *Định dạng yêu cầu không hợp lệ* |
| `InvalidFormat` | 422 | *Định dạng trường không hợp lệ* |
| `InvalidEmail` | 422 | *Email không hợp lệ* |
| `PasswordTooShort` | 422 | *Mật khẩu phải có ít nhất 8 ký tự* |
| `InvalidPagination` | 400 | *Tham số phân trang không hợp lệ* |
| `InvalidFile` | 422 | *File CSV không hợp lệ hoặc quá lớn* |
| `RoomGpsRequired` | 422 | *Vui lòng cấu hình tọa độ GPS phòng học trước khi mở buổi* |

### 4.4 Check-in outcomes

| outcome / errorCode | HTTP | Vietnamese message (default) | BR |
| --- | --- | --- | --- |
| `Success` | 200 | *Điểm danh thành công* | — |
| `ExpiredQr` | 400 | *Mã QR đã hết hạn, vui lòng quét mã mới* | BR-03 |
| `OutOfRadius` | 400 | *Bạn đang ngoài phạm vi phòng học...* | BR-02 |
| `DuplicateCheckIn` | 409 | *Bạn đã điểm danh buổi học này rồi* | BR-04 |
| `GpsDisabled` | 400 | *Vui lòng bật GPS và cấp quyền định vị để điểm danh* | BR-12 |
| `SpoofSuspected` | 400 | *Không thể xác minh vị trí. Liên hệ giảng viên.* | FR-10 |
| `TokenNotFound` | 404 | *Mã QR không hợp lệ* | — |
| `TokenAlreadyUsed` | 400 | *Mã QR đã được sử dụng* | BR-11 |

Canonical mapping table: [05-api-design.md](./05-api-design.md) §6.3.

### 4.5 Session and state

| errorCode | HTTP | Vietnamese message (default) |
| --- | --- | --- |
| `InvalidSessionState` | 409 | *Không thể thực hiện thao tác ở trạng thái buổi học hiện tại* |
| `NotFound` | 404 | *Không tìm thấy dữ liệu* |
| `Conflict` | 409 | *Dữ liệu đã thay đổi. Vui lòng tải lại.* |

### 4.6 Operational

| errorCode | HTTP | Vietnamese message (default) |
| --- | --- | --- |
| `RateLimitExceeded` | 429 | *Quá nhiều yêu cầu. Vui lòng thử lại sau.* |
| `InternalError` | 500 | *Đã xảy ra lỗi. Vui lòng thử lại.* |
| `ServiceUnavailable` | 503 | *Hệ thống tạm thời không khả dụng* |

---

## 5. Retry and Idempotency Policy

| Operation | Idempotent | Client retry guidance |
| --- | --- | --- |
| `GET` requests | Yes | Safe to retry on network error |
| `POST /check-in` | No | Retry up to **3** times within **30 seconds** on network timeout only; do not retry on `409 DuplicateCheckIn` or other `4xx` ([R-01](../brds/07-non-functional-risk.md)) |
| `POST /auth/login` | No | Do not auto-retry on `401`; respect `429 Retry-After` |
| `POST /sessions/:id/open` | No | Fetch session state before retry on `409` |
| `PATCH` attendance | Yes with version | Retry with same body if no response; use optimistic version |
| CSV import | No | Poll `GET /roster/imports/:batchId` after `202 Accepted` |

**Conflict errors:** Clients must refresh entity state before retrying writes that returned `409`.

**Check-in ambiguity:** If client receives no response after timeout, call `GET /attendance/me/history` or session status before submitting again to avoid duplicate attempts.

---

## 6. Logging and Audit Correlation

### 6.1 Structured request logs

Every API request emits one log line (JSON) on completion ([NFR-21](../brds/07-non-functional-risk.md)):

```json
{
  "level": "info",
  "timestamp": "2026-06-28T08:05:12.123Z",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "method": "POST",
  "path": "/api/v1/check-in",
  "status": 400,
  "errorCode": "OutOfRadius",
  "userId": "uuid",
  "sessionId": "uuid",
  "durationMs": 45
}
```

**Never log:** passwords, session secrets, raw `latitude`/`longitude`, full cookie values.

### 6.2 Security and audit events

Append-only audit records ([NFR-15](../brds/07-non-functional-risk.md)):

| Event | Trigger | Stored fields |
| --- | --- | --- |
| `AttendanceManualEdit` | `PATCH /attendance/:id` | actor, record, before/after status, note |
| `ExportAuditLog` | Successful CSV export | actor, filter params, row count |
| `ExportDenied` | Failed export authorization | actor, reason |
| `TokenReuseAlert` | Second student uses consumed token | session, token, student IDs |
| `SpoofFlagged` | `SpoofSuspected` outcome | session, student, heuristic signals (not raw coords) |
| `LoginFailure` | Repeated failed login | email hash, IP (optional) |

### 6.3 Error log levels

| Level | When |
| --- | --- |
| `warn` | Expected domain rejection (check-in fail, auth deny) |
| `error` | Unhandled exception, DB connection failure |
| `info` | Successful check-in, session open/close |

Check-in failures are `warn`, not `error`, to avoid alert noise during normal classroom operation.

---

## 7. Frontend Error Presentation

| Context | UX behavior | Reference |
| --- | --- | --- |
| Login | Inline field errors from `details[]`; toast for `InvalidCredentials` | AC-02 |
| Check-in mobile | Full-screen outcome card with icon; actionable text for `GpsDisabled`, `OutOfRadius` | AC-08, NFR-19 |
| Instructor dashboard | Toast on API failure; preserve polling state | FR-15 |
| Admin forms | Map `details[].field` to form inputs | FR-01 |
| Export | Modal on `403 Forbidden` with admin contact hint | BR-09 |

Global network failure: Vietnamese banner *Không có kết nối mạng* with retry button (check-in only).

---

## 8. Middleware Error Flow

```mermaid
sequenceDiagram
    participant C as Client
    participant M as Middleware chain
    participant H as Handler
    participant D as Domain service
    participant L as Logger

    C->>M: HTTP request
    M->>M: Assign requestId
    M->>H: Forward if auth OK
    H->>D: Business operation
    alt Domain rejection
        D-->>H: DomainError(errorCode)
        H-->>M: Mapped HTTP + body
        M->>L: warn log
        M-->>C: 4xx JSON
    alt Unhandled error
        D-->>H: throw Error
        H-->>M: catch → 500
        M->>L: error log + stack
        M-->>C: 500 generic message
    else Success
        D-->>H: Result
        H-->>C: 2xx JSON
    end
```

Implementation: centralized `ErrorMapper` translates domain exceptions to HTTP + `errorCode`. Unknown errors become `InternalError`.

---

## 9. Local Development Failure Drills

Developers validate error behavior before merge:

| Drill | Steps | Expected |
| --- | --- | --- |
| Expired QR | Submit token aged > 30 s | `400 ExpiredQr`, attempt row persisted |
| Duplicate check-in | Two submissions same student | First `200`, second `409 DuplicateCheckIn` |
| Parallel race | 20 concurrent check-ins same student | Exactly one `Present` ([AC-09c](../brds/08-acceptance-mvp-future.md)) |
| Out of scope report | Instructor calls unassigned class report | `403 Forbidden` |
| GPS disabled | Submit without coordinates | `400 GpsDisabled` |
| Token reuse | Two students, same token | Second rejected; security log entry ([AC-09b](../brds/08-acceptance-mvp-future.md)) |
| Rate limit | 11 check-ins in 10 min | `429` with `Retry-After` |

Run drills against local PostgreSQL via [10-local-development-setup.md](./10-local-development-setup.md).

---

## 10. Traceability Matrix

| Concern | FR | BR | AC | NFR |
| --- | --- | --- | --- | --- |
| Auth errors | FR-02 | BR-06 | AC-02 | NFR-10 |
| Check-in outcomes | FR-07–FR-10 | BR-02–BR-04, BR-11, BR-12 | AC-07–AC-10 | NFR-04, NFR-12 |
| Authorization | FR-12, FR-13 | BR-08, BR-09 | AC-12, AC-13 | NFR-11 |
| Manual edit errors | FR-11 | BR-10 | AC-11 | NFR-15 |
| Logging | — | — | — | NFR-21 |
| Vietnamese messages | — | — | — | NFR-17 |

---

## 11. Future Consideration

| Enhancement | Error handling impact |
| --- | --- |
| Problem Details (RFC 7807) | `application/problem+json` alternate envelope |
| i18n framework | Externalize message catalog; support English UI toggle |
| Webhook failure notifications | Retry queue with dead-letter for IT Operations |
| Sentry / APM integration | Attach `requestId` to external error tracker |
| Offline check-in queue | New error codes for sync conflicts |
