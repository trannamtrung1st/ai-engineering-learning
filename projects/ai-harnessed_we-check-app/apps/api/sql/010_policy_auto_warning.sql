-- Default auto-warning policy toggle (FR-16, BR-05)

INSERT INTO policy_settings (key, value)
VALUES ('absence_auto_warning_enabled', 'false')
ON CONFLICT (key) DO NOTHING;
