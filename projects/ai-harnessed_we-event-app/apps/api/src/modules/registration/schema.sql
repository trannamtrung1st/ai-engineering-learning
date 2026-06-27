-- Registration module schema (Postgres via Docker Compose)

CREATE TABLE IF NOT EXISTS registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  participant_id UUID NOT NULL,
  state TEXT NOT NULL DEFAULT 'Requested',
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cancelled_at TIMESTAMPTZ,
  status_reason_code TEXT,
  status_reason_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  version INT NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_registration
  ON registrations(event_id, participant_id)
  WHERE state IN ('Requested', 'Registered', 'Waitlisted', 'CheckedIn');

CREATE INDEX IF NOT EXISTS idx_reg_event_state
  ON registrations(event_id, state);

CREATE INDEX IF NOT EXISTS idx_reg_participant
  ON registrations(participant_id);

CREATE TABLE IF NOT EXISTS waitlist_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  registration_id UUID NOT NULL UNIQUE REFERENCES registrations(id) ON DELETE CASCADE,
  position INT NOT NULL,
  enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  promoted_at TIMESTAMPTZ,
  expired_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_waitlist_event_position_active
  ON waitlist_entries(event_id, position)
  WHERE promoted_at IS NULL AND expired_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_waitlist_event_queue
  ON waitlist_entries(event_id, position)
  WHERE promoted_at IS NULL AND expired_at IS NULL;

-- Legacy harness DBs may use registration_state enum column name
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'registrations'
      AND column_name = 'registration_state'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'registrations'
      AND column_name = 'state'
  ) THEN
    ALTER TABLE registrations RENAME COLUMN registration_state TO state;
  END IF;
END $$;

-- Idempotent column adds for harness iterations that created schema without audit columns
ALTER TABLE registrations
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;

UPDATE registrations
SET created_at = requested_at
WHERE created_at IS NULL;
