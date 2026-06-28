-- Session-management module: sessions, attendance records, QR tokens

DO $$ BEGIN
  CREATE TYPE session_status AS ENUM ('Draft', 'Active', 'Closed', 'Cancelled');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE attendance_status AS ENUM ('Pending', 'Present', 'Absent', 'Excused', 'Rejected');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE qr_token_status AS ENUM ('Valid', 'Expired', 'Consumed');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY,
  instructor_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  class_id UUID NOT NULL REFERENCES classes (id) ON DELETE RESTRICT,
  subject_id UUID NOT NULL REFERENCES subjects (id) ON DELETE RESTRICT,
  title VARCHAR(200) NOT NULL,
  room_name VARCHAR(100) NOT NULL,
  room_latitude DOUBLE PRECISION NULL,
  room_longitude DOUBLE PRECISION NULL,
  gps_radius_meters INTEGER NOT NULL DEFAULT 100,
  scheduled_start TIMESTAMPTZ NOT NULL,
  status session_status NOT NULL DEFAULT 'Draft',
  opened_at TIMESTAMPTZ NULL,
  closed_at TIMESTAMPTZ NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT sessions_gps_radius_check CHECK (gps_radius_meters BETWEEN 20 AND 500),
  CONSTRAINT sessions_opened_at_check CHECK (
    (status IN ('Active', 'Closed') AND opened_at IS NOT NULL)
    OR (status IN ('Draft', 'Cancelled'))
  )
);

CREATE INDEX IF NOT EXISTS sessions_instructor_id_idx ON sessions (instructor_id);
CREATE INDEX IF NOT EXISTS sessions_class_subject_idx ON sessions (class_id, subject_id);
CREATE INDEX IF NOT EXISTS sessions_status_idx ON sessions (status);
CREATE INDEX IF NOT EXISTS sessions_scheduled_start_idx ON sessions (scheduled_start);

CREATE TABLE IF NOT EXISTS attendance_records (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE RESTRICT,
  student_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  status attendance_status NOT NULL DEFAULT 'Pending',
  checked_in_at TIMESTAMPTZ NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT attendance_records_session_student_key UNIQUE (session_id, student_id)
);

CREATE INDEX IF NOT EXISTS attendance_records_session_id_idx ON attendance_records (session_id);
CREATE INDEX IF NOT EXISTS attendance_records_student_id_idx ON attendance_records (student_id);

CREATE TABLE IF NOT EXISTS qr_tokens (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE RESTRICT,
  status qr_token_status NOT NULL DEFAULT 'Valid',
  issued_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ NULL,
  consumed_by_student_id UUID NULL REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT qr_tokens_expires_after_issued CHECK (expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS qr_tokens_session_id_idx ON qr_tokens (session_id);
CREATE INDEX IF NOT EXISTS qr_tokens_session_status_idx ON qr_tokens (session_id, status);
