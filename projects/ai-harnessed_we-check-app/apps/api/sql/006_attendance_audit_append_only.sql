-- NFR-15 append-only: attendance manual-edit audit rows must not be mutated after insert

CREATE OR REPLACE FUNCTION prevent_attendance_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'attendance_audit_logs is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS attendance_audit_logs_no_update ON attendance_audit_logs;
CREATE TRIGGER attendance_audit_logs_no_update
  BEFORE UPDATE OR DELETE ON attendance_audit_logs
  FOR EACH ROW EXECUTE FUNCTION prevent_attendance_audit_mutation();
