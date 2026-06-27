-- Idempotency key storage for safe write retries (see docs/technical/05-api-design.md)

CREATE TABLE IF NOT EXISTS idempotency_keys (
  actor_id UUID NOT NULL,
  idempotency_key TEXT NOT NULL,
  operation_scope TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  response_status INT NOT NULL,
  response_body JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (actor_id, idempotency_key, operation_scope)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_created
  ON idempotency_keys(created_at);
