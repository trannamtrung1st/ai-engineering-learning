-- Eligibility module schema (Postgres via Docker Compose)

CREATE TABLE IF NOT EXISTS certificate_eligibilities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  registration_id UUID NOT NULL UNIQUE REFERENCES registrations(id) ON DELETE CASCADE,
  participant_id UUID NOT NULL,
  result TEXT NOT NULL DEFAULT 'PendingEvaluation'
    CHECK (result IN ('PendingEvaluation', 'Eligible', 'NotEligible', 'Revoked')),
  reason_code TEXT,
  reason_text TEXT,
  evaluated_at TIMESTAMPTZ,
  overridden_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  version INTEGER NOT NULL DEFAULT 1,
  CONSTRAINT eligibility_reason_when_resolved CHECK (
    (result = 'PendingEvaluation' AND reason_code IS NULL AND reason_text IS NULL)
    OR (
      result IN ('Eligible', 'NotEligible', 'Revoked')
      AND reason_code IS NOT NULL
      AND reason_text IS NOT NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_eligibility_event
  ON certificate_eligibilities(event_id);

CREATE INDEX IF NOT EXISTS idx_eligibility_result
  ON certificate_eligibilities(event_id, result);

ALTER TABLE certificate_eligibilities
  ADD COLUMN IF NOT EXISTS participant_id UUID,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

UPDATE certificate_eligibilities ce
SET participant_id = r.participant_id
FROM registrations r
WHERE ce.registration_id = r.id
  AND ce.participant_id IS NULL;
