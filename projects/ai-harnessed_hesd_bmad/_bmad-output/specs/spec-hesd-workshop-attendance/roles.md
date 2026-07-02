# Roles

Distinct roles with separate surfaces in the MVP.

## Admin

Owns **metadata and configuration** via dedicated admin pages:

- Provision student accounts (manual entry or CSV bulk import)
- Manage workshop rosters (manual entry or CSV import)
- Review audit logs and system-wide attendance metadata

Admin does **not** run live workshop sessions.

## Instructor

Owns **live session operations** and **student interaction**:

- Create and configure workshop sessions (geofence, roster binding)
- Activate sessions and display dynamic QR
- Monitor realtime attendance during a session
- Manually mark or correct attendance for exceptions
- Export session attendance CSV after the workshop

## Student

- Signs in with an admin-provisioned account
- Checks in via mobile web by scanning the session QR

## Permission matrix

| Action | Admin | Instructor | Student |
|--------|-------|------------|---------|
| Provision student accounts | ✓ | — | — |
| Manage rosters (manual / CSV) | ✓ | — | — |
| Create / configure sessions | — | ✓ | — |
| Activate session / display QR | — | ✓ | — |
| Realtime attendance dashboard | — | ✓ | — |
| Manual attendance override | — | ✓ | — |
| Export session CSV | — | ✓ | — |
| Check in via mobile web | — | — | ✓ |
| View audit logs (admin pages) | ✓ | — | — |
