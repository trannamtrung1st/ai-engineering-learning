# State Patterns

| State | Surface | Treatment |
|---|---|---|
| Session draft | Instructor | Yellow banner: "Chưa sẵn sàng — cần gắn danh sách và vùng GPS." |
| Session scheduled | Instructor | `[ASSUMPTION]` Read-only preview; "Kích hoạt" promotes to Active |
| Session active | Instructor + Student | QR live; check-in open |
| Session closed | All | Student link shows closed message; export available |
| QR token expired (mid-scan) | Student | `token_expired` outcome; CTA "Quét lại mã QR" |
| GPS denied | Student | Error panel + steps to enable location; attempt logged |
| First-login password | Student | Full-screen gate before check-in form |
| Import partial failure | Admin | Keep successful rows; highlight failures; allow re-upload fixed CSV |
| Dashboard loading | Instructor | Skeleton rows; live indicator grey until first poll |
| Empty roster | Instructor session create | Block activation; link to contact Admin |
| 150-row table | Instructor | `[ASSUMPTION]` Search/filter by name or student_id; no infinite scroll without filter |
