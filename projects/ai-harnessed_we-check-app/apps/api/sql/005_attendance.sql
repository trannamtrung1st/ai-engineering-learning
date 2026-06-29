-- Attendance module: manual edit audit trail

CREATE TABLE IF NOT EXISTS attendance_audit_logs (
  id UUID PRIMARY KEY,
  attendance_record_id UUID NOT NULL REFERENCES attendance_records (id) ON DELETE RESTRICT,
  editor_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  previous_status attendance_status NOT NULL,
  new_status attendance_status NOT NULL,
  note VARCHAR(500) NULL,
  edited_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS attendance_audit_logs_record_id_idx
  ON attendance_audit_logs (attendance_record_id, edited_at DESC);
