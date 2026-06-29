-- Checkin-qr module: check-in attempts and security audit logs

DO $$ BEGIN
  CREATE TYPE check_in_outcome AS ENUM (
    'Success',
    'ExpiredQr',
    'OutOfRadius',
    'DuplicateCheckIn',
    'GpsDisabled',
    'Unauthenticated',
    'SessionNotActive',
    'SpoofSuspected',
    'NotEnrolled',
    'TokenNotFound',
    'TokenAlreadyUsed'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS check_in_attempts (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE RESTRICT,
  student_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  qr_token_id UUID NULL REFERENCES qr_tokens (id) ON DELETE SET NULL,
  outcome check_in_outcome NOT NULL,
  attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  distance_meters NUMERIC(8, 2) NULL,
  spoof_flags JSONB NULL,
  client_user_agent VARCHAR(512) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS check_in_attempts_session_id_idx
  ON check_in_attempts (session_id, attempted_at DESC);
CREATE INDEX IF NOT EXISTS check_in_attempts_student_session_idx
  ON check_in_attempts (student_id, session_id);
CREATE INDEX IF NOT EXISTS check_in_attempts_outcome_idx
  ON check_in_attempts (outcome, attempted_at);

CREATE TABLE IF NOT EXISTS security_audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type VARCHAR(64) NOT NULL,
  session_id UUID NULL REFERENCES sessions (id) ON DELETE SET NULL,
  qr_token_id UUID NULL REFERENCES qr_tokens (id) ON DELETE SET NULL,
  student_id UUID NULL REFERENCES users (id) ON DELETE SET NULL,
  details JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS security_audit_logs_event_type_idx
  ON security_audit_logs (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS security_audit_logs_session_id_idx
  ON security_audit_logs (session_id, created_at DESC);
