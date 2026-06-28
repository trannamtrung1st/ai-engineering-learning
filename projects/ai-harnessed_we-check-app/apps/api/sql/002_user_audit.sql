-- User state audit for admin provisioning and deactivation (identity-auth)
CREATE TABLE IF NOT EXISTS user_audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users (id),
  actor_id UUID NOT NULL REFERENCES users (id),
  action VARCHAR(64) NOT NULL,
  reason VARCHAR(500) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_audit_logs_user_id_idx ON user_audit_logs (user_id, created_at DESC);
