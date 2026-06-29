-- Reporting-export module: CSV export audit trail

CREATE TABLE IF NOT EXISTS export_audit_logs (
  id UUID PRIMARY KEY,
  admin_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  filter_summary JSONB NOT NULL,
  exported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  row_count INTEGER NOT NULL CHECK (row_count >= 0)
);

CREATE INDEX IF NOT EXISTS export_audit_logs_admin_id_idx
  ON export_audit_logs (admin_id, exported_at DESC);
