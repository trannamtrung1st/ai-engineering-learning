-- Reset auto-warning policy default to off per FR-16 component doc §7.3

UPDATE policy_settings
SET value = 'false'
WHERE key = 'absence_auto_warning_enabled'
  AND value = 'true';

INSERT INTO policy_settings (key, value)
VALUES ('absence_auto_warning_enabled', 'false')
ON CONFLICT (key) DO NOTHING;
