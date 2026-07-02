# Voice and Tone

Brand posture (bold, honest validation) lives in `../design/1-brand-and-style.md`. Microcopy rules:

| Audience | Do | Don't |
|---|---|---|
| Student (VI) | "Bạn đã điểm danh thành công." / "Cần bật vị trí để điểm danh." | "Lỗi hệ thống" without next step |
| Instructor (VI) | "Phiên đang hoạt động — hiển thị mã QR." | Gamified streaks or urgency theater |
| Admin (EN) | "3 rows failed — duplicate email in row 12." | Vague "import failed" |
| All | Name the validation step that failed | Blame the user ("you failed") |

## Failure reason codes

Student-facing Vietnamese labels tied to codes:

| Code | Meaning |
|------|---------|
| `gps_denied` | Location permission required |
| `gps_out_of_range` | Outside geofence |
| `already_checked_in` | Duplicate attempt |
| `not_on_roster` | Not on cohort roster |
| `token_expired` | QR rotated; scan again |
