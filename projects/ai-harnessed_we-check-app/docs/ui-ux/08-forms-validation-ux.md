# We Check — Forms and Validation UX

Form patterns, validation timing, and error presentation for **We Check** MVP. All forms use React Hook Form with Zod schemas from `@wecheck/domain` per [05-common-ui-components.md](./05-common-ui-components.md) §3.

**Related documents:** [Event-specific components](./07-event-specific-components.md) · [Technical validation rules](../technical/08-validation-rules.md) · [Error handling](../technical/09-error-handling.md) · [UI/UX foundation](./01-ui-ux-foundation.md) · [Business rules](../brds/04-business-rules.md)

---

## 1. Form Architecture

| Layer | Responsibility |
| --- | --- |
| Zod schema (`@wecheck/domain`) | Field rules, cross-field validation, Vietnamese error messages |
| React Hook Form | Field state, submit handling, `mode` configuration |
| `FormField` wrapper | Label, description, `aria-describedby`, error display |
| API layer | Server-side validation mapped to field or form-level errors |

**Import rule:** Pages never define inline Zod schemas — reuse shared schemas so client and server stay aligned ([08-validation-rules.md](../technical/08-validation-rules.md)).

---

## 2. Validation Timing

| Event | When applied | Rationale |
| --- | --- | --- |
| On blur | Text inputs, selects, date fields | Reduces noise while typing; catches mistakes before submit |
| On change | Toggles, switches, radio groups | Immediate feedback for discrete choices |
| On submit | All fields | Final gate; scrolls to first error |
| Async on blur | Email, student ID uniqueness | Debounced **300 ms** server check for admin user form |

Default RHF mode: `onBlur` with `reValidateMode: "onChange"` after first submit attempt.

**Mobile student forms** (`/check-in` consent): validate on submit only to minimize interruption during time-sensitive check-in.

---

## 3. Error Presentation

### 3.1 Field-level errors

- Render below control via `FieldError` in `--color-danger-600`.
- Set `aria-invalid="true"` on input.
- Link error text with `aria-describedby`.
- Icon optional on desktop/narrow layouts; never icon-only without text.

### 3.2 Form-level errors

Use `Alert` variant `danger` at top of form for:

- Non-field API errors (e.g., *Phiên đăng nhập đã hết hạn*).
- Cross-field failures (e.g., date range invalid).
- Blocked business rules (e.g., [BR-07](../brds/04-business-rules.md) missing GPS on session open).

On submit failure, focus moves to form-level alert if no field errors; otherwise first invalid field.

### 3.3 Server validation mapping

API returns `{ errorCode, message, fieldErrors?: Record<string, string> }`.

| Response | UX |
| --- | --- |
| `fieldErrors` present | Map to RHF `setError` per field |
| Single business rule violation | Form-level `Alert` with localized `message` |
| HTTP 409 duplicate | Field error on conflicting ID/email |
| HTTP 403 | Redirect to `ForbiddenPage`; no inline form error |

Toast complements form errors for background saves; primary feedback stays inline on forms.

### 3.4 Success feedback

- Create/update forms: toast *Đã lưu thành công* + navigate or reset per form spec.
- Destructive confirms: close dialog + toast on success.
- Check-in: `CheckInOutcomePanel` instead of toast ([07-event-specific-components.md](./07-event-specific-components.md) §2).

---

## 4. Form Catalog

### 4.1 LoginForm

Route: `/login` · [FR-02](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `email` | Email hoặc tên đăng nhập | Required; valid email or institutional username pattern |
| `password` | Mật khẩu | Required; min 8 characters |

**UX:**

- Preserve `returnUrl` query through submit ([BR-06](../brds/04-business-rules.md)).
- Generic failure message: *Email hoặc mật khẩu không đúng* (no account enumeration).
- Submit button: **Đăng nhập**; loading state during auth.
- `Card` width max **400 px** inside `AuthLayout`.

**Traceability:** FR-02 · BR-06 · AC-02 · NFR-16

### 4.2 SessionForm

Route: `/sessions/new`, `/sessions/:id/settings` · [FR-04](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `classCode` | Lớp | Required; must match instructor assignment |
| `subjectCode` | Môn học | Required |
| `title` | Tên buổi học | Required; 3–120 characters |
| `scheduledStartAt` | Thời gian bắt đầu | Required; not in past beyond 24 h grace for draft edits |
| `roomName` | Phòng học | Required; 2–80 characters |
| `latitude` | Vĩ độ | Required; -90 to 90 |
| `longitude` | Kinh độ | Required; -180 to 180 |
| `radiusMeters` | Bán kính GPS (m) | Optional; integer 20–500; default **100** |

**UX:**

- `SplitView` on `lg+`: form left, `GpsMapPicker` right ([06-app-layout-components.md](./06-app-layout-components.md) §9.3).
- Map pin drag syncs lat/lng fields bidirectionally.
- Tooltip on radius: *Sinh viên phải ở trong bán kính này so với tọa độ phòng để điểm danh*.
- Editable only in `Draft`; read-only `DescriptionList` when `Active` or `Closed`.
- **Lưu nháp** saves without opening; **Mở buổi học** validates then calls open transition (blocked if GPS invalid per [BR-07](../brds/04-business-rules.md)).

**Traceability:** FR-04, FR-05 · BR-07 · AC-04

### 4.3 AttendanceEditForm

Dialog form · [FR-11](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `status` | Trạng thái mới | Required; enum Present, Absent, Excused, Rejected |
| `note` | Ghi chú | Required when status is Excused or Rejected; min 10, max 500 characters |

**UX:**

- Show current status as read-only above fields.
- Countdown banner when within 24-hour post-close window: *Còn {hours} giờ để chỉnh sửa*.
- After window: form disabled for `Instructor` with message *Liên hệ phòng đào tạo để chỉnh sửa*.
- Confirm button label: **Cập nhật điểm danh**.

**Traceability:** FR-11 · BR-10 · AC-11

### 4.4 UserForm

Route: `/admin/users/new`, `/admin/users/:id` · [FR-01](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `institutionalId` | Mã SV / Mã cán bộ | Required; unique; alphanumeric |
| `displayName` | Họ và tên | Required; 2–100 characters |
| `email` | Email | Required; valid email; unique async |
| `role` | Vai trò | Required; Student, Instructor, TrainingOfficeAdmin |
| `active` | Đang hoạt động | Boolean; default true |

**UX:**

- Async duplicate check on `institutionalId` and `email` blur.
- Role change to admin requires `ConfirmDialog`: *Cấp quyền quản trị cho tài khoản này?*
- Deactivate via separate confirm, not inline toggle on edit form.

**Traceability:** FR-01 · AC-01 · NFR-11

### 4.5 RosterImportForm

Route: `/admin/rosters/import` · [FR-03](../brds/03-functional-requirements.md)

| Step | Validation |
| --- | --- |
| File select | Required; `.csv` only; max 5 MB |
| Preview | Column headers must match template |
| Row validation | Per-row Zod; errors shown in preview table |

**UX:**

- **Tải mẫu CSV** link downloads template with headers.
- Cannot proceed to import if any row errors unless user fixes file.
- Partial import never silent: summary lists accepted and rejected counts.
- Sticky **Nhập danh sách** button disabled until validation passes.

**Traceability:** FR-03 · AC-03

### 4.6 ReportFilterForm

Routes: `/reports`, `/admin/reports` · [FR-12](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `classCode` | Lớp | Required for instructor; optional all for admin |
| `subjectCode` | Môn học | Required when class selected |
| `dateFrom` | Từ ngày | Required; valid date |
| `dateTo` | Đến ngày | Required; ≥ `dateFrom` |

**UX:**

- Subject `Select` disabled until class chosen.
- **Áp dụng** applies filters to URL query params for shareable report links.
- Invalid range: inline error on `dateTo` field.

**Traceability:** FR-12 · BR-08 · AC-12

### 4.7 CsvExportConfirmForm

Route: `/admin/export` · [FR-13](../brds/03-functional-requirements.md)

Not a traditional form — `ConfirmDialog` with read-only filter summary inherited from `ReportFilterForm`.

| Display | Content |
| --- | --- |
| Scope summary | Class, subject, date range, estimated row count |
| Compliance note | *Dữ liệu xuất chỉ dùng cho mục đích học vụ. Mọi lần xuất được ghi nhật ký.* |
| Confirm | **Xuất CSV** |
| Cancel | **Hủy** |

Disabled when estimated rows = 0: *Không có dữ liệu phù hợp với bộ lọc hiện tại*.

**Traceability:** FR-13 · BR-09 · AC-13

### 4.8 AttendancePolicyForm

Route: `/admin/policy` · [FR-16](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `absenceThresholdPercent` | Ngưỡng vắng (%) | Integer 1–100; default 20 |
| `autoWarningEnabled` | Gửi cảnh báo tự động | Boolean |

**UX:**

- Helper text: *Sinh viên vượt ngưỡng sẽ nhận cảnh báo cùng giảng viên phụ trách* ([BR-05](../brds/04-business-rules.md)).
- Save requires explicit **Lưu chính sách** — no auto-save.

**Traceability:** FR-16 · BR-05 · AC-16

### 4.9 LocationConsentForm

Embedded in first check-in · [FR-08](../brds/03-functional-requirements.md)

| Field | Label | Validation |
| --- | --- | --- |
| `consentAccepted` | Tôi đồng ý cho phép xác minh vị trí trong buổi học | Must be true to proceed |

**UX:**

- Link *Chính sách xử lý dữ liệu* opens modal with NĐ 13/2023 summary.
- Single checkbox + **Tiếp tục** button.
- Shown once per browser; stored in localStorage.

**Traceability:** FR-08 · NFR-17 · AC-08

---

## 5. Submit and Cancel Patterns

### 5.1 FormActions layout

| Viewport | Placement |
| --- | --- |
| Mobile (student) | Sticky footer with safe-area inset; primary right |
| Desktop | Inline footer right-aligned; secondary cancel left of primary |

| Action | Variant | Label convention |
| --- | --- | --- |
| Primary submit | `primary` | Verb: **Lưu**, **Đăng nhập**, **Cập nhật** |
| Secondary cancel | `outline` or `ghost` | **Hủy**, **Quay lại** |
| Destructive | `danger` in dialog | **Hủy buổi học**, **Vô hiệu hóa tài khoản** |

### 5.2 Unsaved changes

Forms with dirty state show browser `beforeunload` prompt on navigation away. In-app navigation intercept shows `ConfirmDialog`: *Thay đổi chưa được lưu. Bạn có chắc muốn rời trang?*

Applies to: `SessionForm`, `UserForm`, `AttendancePolicyForm`.

### 5.3 Loading and double-submit

- Submit disables all actions and sets `aria-busy="true"`.
- Ignore duplicate submit while request in flight.
- On network error: re-enable submit; show retry `Alert`.

---

## 6. Accessibility Requirements

| Requirement | Implementation |
| --- | --- |
| Labels | Every input has visible `<Label>`; no placeholder-only labels |
| Required fields | Asterisk in label + `aria-required="true"` |
| Error announcement | `role="alert"` on first field error after submit |
| Focus management | Dialog forms trap focus; return focus to trigger on close |
| Date inputs | Native `type="date"` with `lang="vi-VN"` on form |
| Touch targets | Min **44 px** height on mobile student forms ([NFR-20](../brds/07-non-functional-risk.md)) |

Full audit checklist: [13-accessibility-basics.md](./13-accessibility-basics.md) (downstream).

---

## 7. Vietnamese Message Catalog

All Zod and API messages use `@wecheck/domain` catalog keys. Representative samples:

| Key | Message |
| --- | --- |
| `validation.required` | Trường này là bắt buộc |
| `validation.email` | Email không hợp lệ |
| `validation.minLength` | Tối thiểu {min} ký tự |
| `validation.latitude` | Vĩ độ phải từ -90 đến 90 |
| `validation.longitude` | Kinh độ phải từ -180 đến 180 |
| `validation.dateRange` | Ngày kết thúc phải sau ngày bắt đầu |
| `validation.duplicateId` | Mã này đã tồn tại trong hệ thống |
| `validation.csv.row` | Dòng {row}: {reason} |

Engineers must not hardcode validation strings in components.

---

## 8. Traceability Matrix

| Form | FR | BR | AC | NFR |
| --- | --- | --- | --- | --- |
| `LoginForm` | FR-02 | BR-06 | AC-02 | NFR-16 |
| `SessionForm` | FR-04, FR-05 | BR-07 | AC-04, AC-05 | — |
| `AttendanceEditForm` | FR-11 | BR-10 | AC-11 | — |
| `UserForm` | FR-01 | — | AC-01 | NFR-11 |
| `RosterImportForm` | FR-03 | — | AC-03 | — |
| `ReportFilterForm` | FR-12 | BR-08 | AC-12 | — |
| `CsvExportConfirmForm` | FR-13 | BR-09 | AC-13 | NFR-11 |
| `AttendancePolicyForm` | FR-16 | BR-05 | AC-16 | — |
| `LocationConsentForm` | FR-08 | — | AC-08 | NFR-17 |

---

## 9. Future Consideration

- Multi-step wizard for session creation (schedule → location → review).
- Inline editable cells in roster table with per-cell validation.
- Autosave draft sessions every 30 seconds.
- Password strength meter and reset flow forms.
- Form analytics (abandon rate, error field heatmap) for pilot tuning.
