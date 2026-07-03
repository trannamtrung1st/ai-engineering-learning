-- Attendly MVP baseline schema (identity, academic structure, session, attendance, policy, audit)
-- Traceability: FR-04, FR-18, BR-06, BR-07, NFR-07

CREATE EXTENSION IF NOT EXISTS citext;

-- Identity
CREATE TABLE users (
  id uuid PRIMARY KEY,
  email citext NOT NULL UNIQUE,
  display_name text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_role_assignments (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  role text NOT NULL CHECK (
    role IN (
      'Student',
      'Lecturer',
      'DepartmentAdmin',
      'AcademicAdmin',
      'ITAdmin',
      'SystemAuditor'
    )
  ),
  scope_type text NOT NULL CHECK (
    scope_type IN ('Institution', 'Faculty', 'Course', 'ClassSection', 'Self')
  ),
  scope_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, role, scope_type, scope_id)
);

CREATE TABLE student_profiles (
  user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  student_code text NOT NULL UNIQUE,
  faculty_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE lecturer_profiles (
  user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  staff_code text NOT NULL UNIQUE,
  faculty_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Academic structure
CREATE TABLE faculties (
  id uuid PRIMARY KEY,
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE terms (
  id uuid PRIMARY KEY,
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  start_date date NOT NULL,
  end_date date NOT NULL CHECK (end_date >= start_date),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE courses (
  id uuid PRIMARY KEY,
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  faculty_id uuid NOT NULL REFERENCES faculties (id),
  credit_units integer CHECK (credit_units IS NULL OR credit_units > 0),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rooms (
  id uuid PRIMARY KEY,
  code text NOT NULL UNIQUE,
  building text,
  name text NOT NULL,
  latitude numeric(9, 6),
  longitude numeric(9, 6),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE class_sections (
  id uuid PRIMARY KEY,
  section_code text NOT NULL,
  term_id uuid NOT NULL REFERENCES terms (id),
  course_id uuid NOT NULL REFERENCES courses (id),
  lecturer_user_id uuid NOT NULL REFERENCES users (id),
  default_room_id uuid REFERENCES rooms (id),
  capacity integer CHECK (capacity IS NULL OR capacity > 0),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (term_id, section_code)
);

CREATE TABLE enrollments (
  id uuid PRIMARY KEY,
  class_section_id uuid NOT NULL REFERENCES class_sections (id) ON DELETE CASCADE,
  student_user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status text NOT NULL CHECK (status IN ('Active', 'Dropped', 'Completed')),
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  dropped_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (class_section_id, student_user_id)
);

-- Session operations
CREATE TABLE class_sessions (
  id uuid PRIMARY KEY,
  class_section_id uuid NOT NULL REFERENCES class_sections (id) ON DELETE CASCADE,
  room_id uuid REFERENCES rooms (id),
  scheduled_start_at timestamptz NOT NULL,
  scheduled_end_at timestamptz NOT NULL CHECK (scheduled_end_at > scheduled_start_at),
  state text NOT NULL CHECK (
    state IN ('Scheduled', 'Open', 'Closed', 'Cancelled')
  ),
  opened_at timestamptz,
  opened_by_user_id uuid REFERENCES users (id),
  closed_at timestamptz,
  closed_by_user_id uuid REFERENCES users (id),
  topic text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE qr_session_tokens (
  id uuid PRIMARY KEY,
  class_session_id uuid NOT NULL REFERENCES class_sessions (id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  state text NOT NULL CHECK (state IN ('Valid', 'Expired', 'Invalid')),
  issued_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL CHECK (expires_at > issued_at),
  sequence_number integer CHECK (sequence_number IS NULL OR sequence_number >= 0)
);

-- Attendance operations
CREATE TABLE check_in_attempts (
  id uuid PRIMARY KEY,
  class_session_id uuid NOT NULL REFERENCES class_sessions (id) ON DELETE CASCADE,
  student_user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  qr_session_token_id uuid REFERENCES qr_session_tokens (id),
  outcome text NOT NULL CHECK (
    outcome IN (
      'Success',
      'ExpiredQr',
      'SessionNotOpen',
      'SessionClosed',
      'NotEnrolled',
      'DuplicateCheckIn',
      'GpsRequired',
      'GpsDisabled',
      'OutOfRadius',
      'LowAccuracy',
      'Unauthenticated',
      'Suspicious'
    )
  ),
  submitted_at timestamptz NOT NULL DEFAULT now(),
  client_timestamp timestamptz,
  gps_latitude numeric(9, 6),
  gps_longitude numeric(9, 6),
  gps_accuracy_meters numeric(7, 2) CHECK (gps_accuracy_meters IS NULL OR gps_accuracy_meters >= 0),
  distance_from_room_meters numeric(8, 2) CHECK (distance_from_room_meters IS NULL OR distance_from_room_meters >= 0),
  gps_validation_result text CHECK (
    gps_validation_result IS NULL
    OR gps_validation_result IN ('Pass', 'Fail', 'Skipped', 'Suspicious')
  ),
  device_user_agent text,
  ip_address inet,
  rejection_reason text,
  correlation_id uuid
);

CREATE TABLE attendance_records (
  id uuid PRIMARY KEY,
  class_session_id uuid NOT NULL REFERENCES class_sessions (id) ON DELETE CASCADE,
  class_section_id uuid NOT NULL REFERENCES class_sections (id) ON DELETE CASCADE,
  student_user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status text NOT NULL CHECK (
    status IN (
      'Pending',
      'Present',
      'Late',
      'Absent',
      'Excused',
      'Manual Present'
    )
  ),
  check_in_method text CHECK (
    check_in_method IS NULL
    OR check_in_method IN ('QR', 'Manual', 'Admin Correction')
  ),
  check_in_at timestamptz,
  last_modified_at timestamptz NOT NULL DEFAULT now(),
  last_modified_by_user_id uuid REFERENCES users (id),
  modification_reason text,
  source_attempt_id uuid REFERENCES check_in_attempts (id),
  UNIQUE (class_session_id, student_user_id)
);

-- Policy and compliance
CREATE TABLE attendance_policies (
  id uuid PRIMARY KEY,
  scope_type text NOT NULL CHECK (
    scope_type IN ('Institution', 'Faculty', 'Course', 'ClassSection')
  ),
  scope_id uuid,
  check_in_opening_offset_minutes integer CHECK (
    check_in_opening_offset_minutes IS NULL
    OR check_in_opening_offset_minutes >= 0
  ),
  present_window_minutes integer NOT NULL CHECK (present_window_minutes > 0),
  late_window_minutes integer NOT NULL CHECK (late_window_minutes >= 0),
  auto_close_enabled boolean NOT NULL DEFAULT true,
  absence_threshold_percent numeric(5, 2) CHECK (
    absence_threshold_percent IS NULL
    OR (absence_threshold_percent >= 0 AND absence_threshold_percent <= 100)
  ),
  excused_counts_toward_threshold boolean NOT NULL DEFAULT false,
  manual_edit_window_hours integer NOT NULL CHECK (manual_edit_window_hours >= 0),
  admin_approval_required boolean NOT NULL DEFAULT false,
  gps_required boolean NOT NULL DEFAULT false,
  gps_radius_meters integer CHECK (gps_radius_meters IS NULL OR gps_radius_meters > 0),
  gps_min_accuracy_meters integer CHECK (
    gps_min_accuracy_meters IS NULL OR gps_min_accuracy_meters > 0
  ),
  effective_from date,
  effective_to date CHECK (
    effective_to IS NULL
    OR effective_from IS NULL
    OR effective_to >= effective_from
  ),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE policy_snapshots (
  id uuid PRIMARY KEY,
  class_session_id uuid NOT NULL REFERENCES class_sessions (id) ON DELETE CASCADE,
  resolved_json jsonb NOT NULL,
  resolved_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id uuid PRIMARY KEY,
  timestamp timestamptz NOT NULL DEFAULT now(),
  actor_user_id uuid REFERENCES users (id),
  action_type text NOT NULL CHECK (
    action_type IN (
      'AttendanceUpdate',
      'Export',
      'SessionOpen',
      'SessionClose',
      'PolicyChange',
      'EnrollmentImport',
      'CheckInAttempt'
    )
  ),
  target_type text NOT NULL,
  target_id uuid NOT NULL,
  old_value jsonb,
  new_value jsonb,
  reason text,
  scope_type text,
  scope_id uuid,
  correlation_id uuid,
  ip_address inet
);

-- Operational indexes (docs/technical/04-database-design.md §6)
CREATE INDEX idx_class_sessions_section_start ON class_sessions (class_section_id, scheduled_start_at);
CREATE INDEX idx_class_sessions_state_start ON class_sessions (state, scheduled_start_at);
CREATE INDEX idx_qr_tokens_session_state_expires ON qr_session_tokens (class_session_id, state, expires_at);
CREATE INDEX idx_check_in_attempts_session_submitted ON check_in_attempts (class_session_id, submitted_at);
CREATE INDEX idx_check_in_attempts_student_submitted ON check_in_attempts (student_user_id, submitted_at);
CREATE INDEX idx_attendance_records_section_status ON attendance_records (class_section_id, status);
CREATE INDEX idx_enrollments_section_status ON enrollments (class_section_id, status);
CREATE INDEX idx_audit_logs_target_timestamp ON audit_logs (target_type, target_id, timestamp);
CREATE INDEX idx_audit_logs_actor_timestamp ON audit_logs (actor_user_id, timestamp);

CREATE INDEX idx_check_in_attempts_rejected ON check_in_attempts (outcome, submitted_at)
  WHERE outcome <> 'Success';

CREATE INDEX idx_class_sessions_open_start ON class_sessions (scheduled_start_at)
  WHERE state = 'Open';

-- Profile FK to faculties (after faculties table exists)
ALTER TABLE student_profiles
  ADD CONSTRAINT student_profiles_faculty_id_fkey
  FOREIGN KEY (faculty_id) REFERENCES faculties (id);

ALTER TABLE lecturer_profiles
  ADD CONSTRAINT lecturer_profiles_faculty_id_fkey
  FOREIGN KEY (faculty_id) REFERENCES faculties (id);
