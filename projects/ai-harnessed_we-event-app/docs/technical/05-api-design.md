# API Design

## 1. API Principles
- REST-style JSON APIs.
- Versioned base path: `/api/v1`.
- Auth required for all non-public endpoints.
- Strict input validation before domain execution.
- Consistent typed errors with stable codes.

## 2. Endpoint Groups
## 2.0 Event Listing
- `GET /events` (paginated; role-filtered event states)
- `GET /events/{eventId}` (single event detail)

## 2.1 Event Management
- `POST /events`
- `PATCH /events/{eventId}`
- `POST /events/{eventId}/publish`
- `POST /events/{eventId}/pause`
- `POST /events/{eventId}/open-registration`
- `POST /events/{eventId}/close-registration`
- `POST /events/{eventId}/start`
- `POST /events/{eventId}/complete`
- `POST /events/{eventId}/cancel`

## 2.2 Registration & Waitlist
- `GET /events/{eventId}/registration-status` (current actor)
- `POST /events/{eventId}/registrations`
- `POST /events/{eventId}/registrations/{registrationId}/cancel`
- `GET /events/{eventId}/registrations`
- `GET /events/{eventId}/waitlist`

## 2.3 Check-in
- `POST /events/{eventId}/checkins` (staff action)
- `POST /events/{eventId}/self-checkin` (participant action, if enabled)
- `GET /events/{eventId}/attendance`

## 2.4 Feedback & Eligibility
- `POST /events/{eventId}/feedback`
- `GET /events/{eventId}/eligibility/me`
- `GET /events/{eventId}/eligibility` (admin/staff-scope)
- `POST /events/{eventId}/eligibility/{registrationId}/revoke`

## 2.5 Monitoring & Audit
- `GET /events/{eventId}/dashboard`
- `GET /events/{eventId}/status-history`
- `GET /events/{eventId}/audit-logs`
- `GET /events/{eventId}/export`

- `GET /events/{eventId}/export`

## 2.6 Participant Self-Service
- `GET /me/registrations` (paginated list of current actor's registrations across events)

## 3. Pagination Contract

All list endpoints below return a **paginated envelope** instead of a bare array. Full-array responses are deprecated.

### Query parameters

| Param | Type | Default | Max | Notes |
|-------|------|---------|-----|-------|
| `page` | int ≥ 1 | 1 | — | 1-based page index |
| `pageSize` | int | endpoint-specific | 100 | See per-endpoint defaults |
| `q` | string | — | — | Optional search (where supported) |
| `sort` | string | endpoint-specific | — | e.g. `startAt:asc`, `updatedAt:desc` |

Invalid `page` or `pageSize` (non-integer, `< 1`, or `pageSize` above max) returns `400` with code `INVALID_PAGINATION`.

### Response envelope

```json
{
  "items": [],
  "page": 1,
  "pageSize": 20,
  "total": 142,
  "totalPages": 8
}
```

- `total`: total matching rows before paging.
- `totalPages`: `ceil(total / pageSize)`.
- Requesting a page beyond `totalPages` returns `items: []` with valid metadata (AC-13).

### Paginated list endpoints

| Endpoint | Default `pageSize` | Default `sort` | Extra filters |
|----------|-------------------|----------------|---------------|
| `GET /events` | 12 | `startAt:asc` | `state` (optional) |
| `GET /events/{eventId}/registrations` | 20 | `updatedAt:desc` | `state` (optional) |
| `GET /events/{eventId}/waitlist` | 20 | `position:asc` | — |
| `GET /events/{eventId}/attendance` | 20 | `checkinAt:desc` | — |
| `GET /events/{eventId}/eligibility` | 20 | `participantId:asc` | `eligibility` (optional) |
| `GET /events/{eventId}/audit-logs` | 20 | `createdAt:desc` | `entityType`, `entityId` |
| `GET /events/{eventId}/status-history` | 20 | `createdAt:desc` | `registrationId` |
| `GET /me/registrations` | 20 | `updatedAt:desc` | `state` (optional) |

### Example: Paginated events list

`GET /api/v1/events?page=2&pageSize=12&q=workshop&sort=startAt:asc`

Response:
```json
{
  "items": [
    {
      "eventId": "uuid",
      "name": "Workshop Series",
      "state": "RegistrationOpen",
      "startAt": "2026-07-01T09:00:00Z",
      "location": "Room A"
    }
  ],
  "page": 2,
  "pageSize": 12,
  "total": 28,
  "totalPages": 3
}
```

### Example: Paginated my registrations

`GET /api/v1/me/registrations?page=1&pageSize=20`

Response:
```json
{
  "items": [
    {
      "registrationId": "uuid",
      "eventId": "uuid",
      "eventName": "Workshop Series",
      "state": "Registered",
      "updatedAt": "2026-06-24T16:00:00Z"
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 5,
  "totalPages": 1
}
```

## 4. Request/Response Contracts
### Example: Register
`POST /api/v1/events/{eventId}/registrations`

Request:
```json
{
  "participantId": "optional-if-derived-from-token"
}
```

Response:
```json
{
  "registrationId": "uuid",
  "eventId": "uuid",
  "participantId": "uuid",
  "state": "Registered",
  "reasonCode": null,
  "updatedAt": "2026-06-24T16:00:00Z"
}
```

### Example: Submit feedback
`POST /api/v1/events/{eventId}/feedback`

Request:
```json
{
  "registrationId": "uuid",
  "answers": {
    "q1": 5,
    "q2": "Great event"
  }
}
```

Response:
```json
{
  "feedbackId": "uuid",
  "submittedAt": "2026-06-24T16:30:00Z"
}
```

## 5. Validation and Guardrails
- Reject registration when outside registration window.
- Reject duplicate active registration for same participant/event.
- Reject check-in outside check-in window.
- Reject feedback from non-registered participants.
- Reject eligibility revocation unless actor is `OrganizerAdmin` and reason is provided.

## 6. Idempotency and Concurrency
- Use `Idempotency-Key` header for write endpoints with possible retries (`register`, `cancel`, `checkin`).
- Mutating endpoints return latest known entity state.
- Server enforces transactional consistency for seat and waitlist operations.

## 7. Error Contract
All errors return:
```json
{
  "error": {
    "code": "REGISTRATION_DUPLICATE_ACTIVE",
    "message": "You already have an active registration for this event.",
    "details": {},
    "requestId": "uuid"
  }
}
```

HTTP mapping:
- `400` invalid input
- `401` unauthenticated
- `403` unauthorized
- `404` entity not found or not in actor scope
- `409` state conflict / duplicate registration / invalid transition
- `422` semantic rule violation

## 8. API-Level Traceability Tags
- Registration endpoints: BR-01..BR-09, AC-01..AC-04
- Check-in endpoints: BR-10..BR-13, AC-05..AC-07
- Feedback/eligibility endpoints: BR-14..BR-20, AC-08..AC-10
- Audit/report endpoints: BR-21..BR-22, AC-11..AC-12
- List pagination: FR-28..FR-31, NFR-16, AC-13..AC-14
