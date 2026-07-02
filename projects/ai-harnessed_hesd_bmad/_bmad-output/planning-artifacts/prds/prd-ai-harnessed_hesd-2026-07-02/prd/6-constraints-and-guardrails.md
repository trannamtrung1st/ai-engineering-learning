# 6. Constraints and Guardrails

## Privacy

- Student location is collected only during Check-In Attempts, not tracked continuously.
- Only Admin and session-bound Instructor see attendance data for their scope.

## Security

- Passwords stored hashed; first-login password change enforced per FR-3a.
- Session Tokens are server-validated; client cannot forge check-in without valid token + auth.
- Initial Admin account is seeded via deployment setup (database seed or bootstrap script) for internal pilot.

---
