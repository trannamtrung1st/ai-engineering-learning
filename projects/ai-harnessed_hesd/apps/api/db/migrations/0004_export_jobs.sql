-- M07 Reporting and Export — async CSV export job metadata (FR-27, FR-30)

CREATE TABLE export_jobs (
  id uuid PRIMARY KEY,
  actor_user_id uuid NOT NULL REFERENCES users (id),
  format text NOT NULL CHECK (format IN ('csv')),
  status text NOT NULL CHECK (
    status IN ('Queued', 'Processing', 'Completed', 'Failed')
  ),
  filters_json jsonb NOT NULL,
  idempotency_key text,
  artifact_csv text,
  row_count integer CHECK (row_count IS NULL OR row_count >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE UNIQUE INDEX idx_export_jobs_actor_idempotency
  ON export_jobs (actor_user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_export_jobs_actor_created ON export_jobs (actor_user_id, created_at DESC);
