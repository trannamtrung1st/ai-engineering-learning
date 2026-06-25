# API Design

## 1. API Principles
- REST-style JSON APIs.
- Versioned base path: `/api/v1`.
- Auth required for all non-public endpoints.
- Strict input validation before domain execution.
- Consistent typed errors with stable codes.

## 2. Endpoint Groups
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

## 3. Request/Response Contracts
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

## 4. Validation and Guardrails
- Reject registration when outside registration window.
- Reject duplicate active registration for same participant/event.
- Reject check-in outside check-in window.
- Reject feedback from non-registered participants.
- Reject eligibility revocation unless actor is `OrganizerAdmin` and reason is provided.

## 5. Idempotency and Concurrency
- Use `Idempotency-Key` header for write endpoints with possible retries (`register`, `cancel`, `checkin`).
- Mutating endpoints return latest known entity state.
- Server enforces transactional consistency for seat and waitlist operations.

## 6. Error Contract
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

## 7. API-Level Traceability Tags
- Registration endpoints: BR-01..BR-09, AC-01..AC-04
- Check-in endpoints: BR-10..BR-13, AC-05..AC-07
- Feedback/eligibility endpoints: BR-14..BR-20, AC-08..AC-10
- Audit/report endpoints: BR-21..BR-22, AC-11..AC-12
