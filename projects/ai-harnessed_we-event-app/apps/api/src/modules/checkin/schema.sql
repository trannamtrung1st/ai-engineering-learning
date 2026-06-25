-- Check-in module schema (Postgres via Docker Compose)

CREATE TABLE IF NOT EXISTS checkin_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  registration_id UUID NOT NULL UNIQUE REFERENCES registrations(id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  checkin_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  method TEXT NOT NULL CHECK (method IN ('Staff', 'Self')),
  operator_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT checkin_staff_operator CHECK (
    (method = 'Staff' AND operator_id IS NOT NULL)
    OR (method = 'Self' AND operator_id IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_checkin_event
  ON checkin_records(event_id);

CREATE INDEX IF NOT EXISTS idx_checkin_at
  ON checkin_records(checkin_at);
