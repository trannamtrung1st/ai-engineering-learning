-- Notifications module: in-app alerts and absence threshold policy (FR-16, BR-05)

DO $$ BEGIN
  CREATE TYPE notification_type AS ENUM ('AbsenceThresholdWarning');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  type notification_type NOT NULL,
  payload JSONB NOT NULL,
  read_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notifications_user_unread_idx
  ON notifications (user_id, created_at DESC)
  WHERE read_at IS NULL;

CREATE INDEX IF NOT EXISTS notifications_user_created_idx
  ON notifications (user_id, created_at DESC, id DESC);

-- Idempotent threshold evaluation per session close (FR-16, TC-FR-16-019)
CREATE UNIQUE INDEX IF NOT EXISTS notifications_absence_dedup_idx
  ON notifications (
    user_id,
    type,
    (payload->>'sourceSessionId'),
    COALESCE(payload->>'studentId', '')
  )
  WHERE type = 'AbsenceThresholdWarning';
