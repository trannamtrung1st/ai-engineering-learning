-- Event module schema (Postgres via Docker Compose)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO organizations (id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default Organization')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'Draft',
  start_at TIMESTAMPTZ NOT NULL,
  end_at TIMESTAMPTZ NOT NULL,
  created_by UUID NOT NULL,
  updated_by UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  version INT NOT NULL DEFAULT 1,
  CONSTRAINT events_start_before_end CHECK (start_at < end_at)
);

CREATE INDEX IF NOT EXISTS idx_events_organization ON events(organization_id);
CREATE INDEX IF NOT EXISTS idx_events_state ON events(state);

CREATE TABLE IF NOT EXISTS event_rule_configs (
  event_id UUID PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
  capacity INT NOT NULL DEFAULT 0,
  waitlist_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  registration_open_at TIMESTAMPTZ NOT NULL,
  registration_close_at TIMESTAMPTZ NOT NULL,
  checkin_open_at TIMESTAMPTZ NOT NULL,
  checkin_close_at TIMESTAMPTZ NOT NULL,
  feedback_required BOOLEAN NOT NULL DEFAULT FALSE,
  feedback_open_at TIMESTAMPTZ NOT NULL,
  feedback_close_at TIMESTAMPTZ NOT NULL,
  registration_paused BOOLEAN NOT NULL DEFAULT FALSE,
  version INT NOT NULL DEFAULT 1,
  CONSTRAINT event_rule_capacity_non_negative CHECK (capacity >= 0),
  CONSTRAINT event_rule_registration_window CHECK (registration_open_at < registration_close_at),
  CONSTRAINT event_rule_checkin_window CHECK (checkin_open_at < checkin_close_at),
  CONSTRAINT event_rule_feedback_window CHECK (feedback_open_at < feedback_close_at)
);

-- Idempotent column add for harness iterations that created schema without pause flag
ALTER TABLE event_rule_configs
  ADD COLUMN IF NOT EXISTS registration_paused BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE events
  ADD COLUMN IF NOT EXISTS cover_image_key TEXT,
  ADD COLUMN IF NOT EXISTS cover_image_updated_at TIMESTAMPTZ;
