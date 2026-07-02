-- M10 Notification — absence-threshold alert events and delivery queue (FR-26, BR-17)

CREATE TABLE policy_alert_events (
  id uuid PRIMARY KEY,
  class_section_id uuid NOT NULL REFERENCES class_sections (id),
  student_user_id uuid NOT NULL REFERENCES users (id),
  alert_type text NOT NULL CHECK (alert_type IN ('AbsenceThreshold')),
  unexcused_absence_rate numeric(5, 2) NOT NULL,
  absence_threshold_percent numeric(5, 2) NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (class_section_id, student_user_id, alert_type)
);

CREATE INDEX idx_policy_alert_events_section_created
  ON policy_alert_events (class_section_id, created_at DESC);

CREATE INDEX idx_policy_alert_events_student_created
  ON policy_alert_events (student_user_id, created_at DESC);

CREATE TABLE notification_delivery_queue (
  id uuid PRIMARY KEY,
  alert_event_id uuid NOT NULL REFERENCES policy_alert_events (id) ON DELETE CASCADE,
  recipient_user_id uuid NOT NULL REFERENCES users (id),
  recipient_role text NOT NULL,
  channel text NOT NULL DEFAULT 'in_app',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_notification_delivery_queue_alert
  ON notification_delivery_queue (alert_event_id);

CREATE INDEX idx_notification_delivery_queue_recipient
  ON notification_delivery_queue (recipient_user_id, created_at DESC);

ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_type_check;

ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_type_check CHECK (
  action_type IN (
    'AttendanceUpdate',
    'Export',
    'SessionOpen',
    'SessionClose',
    'PolicyChange',
    'EnrollmentImport',
    'CheckInAttempt',
    'AbsenceThresholdAlert'
  )
);
