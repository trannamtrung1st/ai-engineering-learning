-- Audit module schema (Postgres via Docker Compose)

CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID REFERENCES events(id) ON DELETE SET NULL,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  action TEXT NOT NULL,
  actor_id UUID NOT NULL,
  actor_role TEXT NOT NULL,
  reason_code TEXT,
  reason_text TEXT,
  before_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  after_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_event ON audit_logs(event_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(event_id, entity_type, entity_id, occurred_at DESC);
