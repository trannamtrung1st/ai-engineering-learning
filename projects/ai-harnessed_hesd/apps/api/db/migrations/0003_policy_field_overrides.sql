-- BR-20 per-field policy precedence — track which fields each scope explicitly overrides
-- Traceability: FR-24, FR-25, BR-20

ALTER TABLE attendance_policies
ADD COLUMN IF NOT EXISTS field_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Institution seed row: all behavioral fields are explicit overrides
UPDATE attendance_policies
SET field_overrides = '{
  "presentWindowMinutes": true,
  "lateWindowMinutes": true,
  "checkInOpeningOffsetMinutes": true,
  "autoCloseEnabled": true,
  "absenceThresholdPercent": true,
  "excusedCountsTowardThreshold": true,
  "manualEditWindowHours": true,
  "adminApprovalRequired": true,
  "gpsRequired": true,
  "gpsRadiusMeters": true,
  "gpsMinAccuracyMeters": true
}'::jsonb
WHERE scope_type = 'Institution'
  AND field_overrides = '{}'::jsonb;
