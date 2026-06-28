-- Roster-enrollment module: classes, subjects, enrollments, assignments, import batches

DO $$ BEGIN
  CREATE TYPE roster_import_status AS ENUM ('Processing', 'Completed', 'Failed');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS classes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  term VARCHAR(64) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subjects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS enrollments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  class_id UUID NOT NULL REFERENCES classes (id) ON DELETE RESTRICT,
  subject_id UUID NOT NULL REFERENCES subjects (id) ON DELETE RESTRICT,
  enrolled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT enrollments_student_class_subject_key UNIQUE (student_id, class_id, subject_id)
);

CREATE INDEX IF NOT EXISTS enrollments_class_subject_idx ON enrollments (class_id, subject_id);
CREATE INDEX IF NOT EXISTS enrollments_student_id_idx ON enrollments (student_id);

CREATE TABLE IF NOT EXISTS class_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instructor_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  class_id UUID NOT NULL REFERENCES classes (id) ON DELETE RESTRICT,
  subject_id UUID NOT NULL REFERENCES subjects (id) ON DELETE RESTRICT,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT class_assignments_instructor_class_subject_key UNIQUE (instructor_id, class_id, subject_id)
);

CREATE INDEX IF NOT EXISTS class_assignments_instructor_id_idx ON class_assignments (instructor_id);

CREATE TABLE IF NOT EXISTS roster_import_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  uploaded_by_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  file_name VARCHAR(255) NOT NULL,
  status roster_import_status NOT NULL DEFAULT 'Processing',
  total_rows INTEGER NOT NULL DEFAULT 0,
  success_rows INTEGER NOT NULL DEFAULT 0,
  error_rows INTEGER NOT NULL DEFAULT 0,
  error_details JSONB NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ NULL
);
