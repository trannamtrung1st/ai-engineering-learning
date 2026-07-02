# Information Architecture

## Admin web (Linh)

| Surface | Nav / entry | Purpose |
|---|---|---|
| Admin dashboard | Sign-in → home | Counts: students, instructors, rosters; quick links to import |
| Students — list | Side nav | Browse provisioned students |
| Students — create | Students → Add | Manual account form (FR-1) |
| Students — CSV import | Students → Import | Bulk provision + per-row results (FR-2) |
| Instructors — list / create | Side nav | Instructor account management (FR-4) |
| Rosters — list | Side nav | Cohort rosters |
| Roster — detail | Roster row | Manual add/edit/remove by student_id (FR-5) |
| Roster — CSV import | Roster detail → Import | Append vs replace choice, per-row errors (FR-6) |
| Audit log | Side nav | Read-only browse/filter (FR-17) |

Admin does **not** operate live Workshop Sessions.

## Instructor web (Minh)

| Surface | Nav / entry | Purpose |
|---|---|---|
| Instructor dashboard | Sign-in → home | Upcoming / active / past sessions |
| Session — create / edit | New session | Title, date/time, roster bind, geofence (FR-7, FR-8) |
| Session — lifecycle | Session detail | draft → scheduled → active → closed (FR-9) |
| QR Display | Active session → Show QR | Full-screen projected rotating QR (FR-10) |
| Live attendance | Active session → Dashboard | Realtime table Present/Absent/Failed/Override (FR-14) |
| Manual override | Row action on dashboard | Set Present/Absent + required reason (FR-15) |
| CSV export | Closed or active session | Download attendance (FR-18) |

## Student mobile web (Trang)

| Surface | Entry | Purpose |
|---|---|---|
| Check-in entry | QR scan deep link | Validates session active before auth (FR-11) |
| Sign-in | Entry → login | Email/password; role gate |
| First-login password change | Post-login gate | Blocks check-in until complete (FR-3a) |
| GPS permission | Pre-submit | Location prompt with plain-language why |
| Check-in outcome | Submit | Vietnamese success/failure + reason code (FR-13) |

## Surface closure

| Stated need | Surface |
|---|---|
| Provision 150 students | Students CSV import + results |
| Bind roster to session | Session create + roster picker |
| Project QR in classroom | QR Display |
| Student <1 min check-in | Mobile check-in flow |
| Live headcount | Live attendance dashboard |
| Fix GPS/roster edge cases | Manual override |
| Post-workshop reporting | CSV export |
| Investigate fraud attempts | Admin audit log |
