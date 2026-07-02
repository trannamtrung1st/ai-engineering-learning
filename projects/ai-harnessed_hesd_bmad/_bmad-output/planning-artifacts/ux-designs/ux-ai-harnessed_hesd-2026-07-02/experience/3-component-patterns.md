# Component Patterns

Behavioral. Visual specs in `../design/7-components.md`.

| Component | Surface | Behavioral rules |
|---|---|---|
| Session lifecycle stepper | Instructor session detail | Four states; only **Active** enables QR + check-in; **Closed** locks new check-ins |
| Geofence map | Session create/edit | Pin drag + radius slider 50–200m default 100m; "Use my location" sets pin `[ASSUMPTION]` |
| QR Display | Instructor | Auto-refresh token every 30s; countdown visible; ESC exits to session detail |
| Live attendance table | Instructor | Columns: name, student_id, status, last reason, override action; sticky header; auto-refresh |
| Manual override modal | Instructor | Status toggle + **required** reason textarea; confirm applies immediately |
| CSV import panel | Admin | Template download link; file picker; summary table per-row success/fail |
| Roster import mode | Admin | Radio: Append vs Replace — must choose before upload |
| Check-in CTA | Student | Single primary button; disabled until GPS resolved or error shown |
| Audit log filters | Admin | Session, student, date range, outcome; paginated `[ASSUMPTION]` 50 rows/page |
