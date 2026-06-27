-- User module schema (Postgres via Docker Compose)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower
  ON users (lower(email));

CREATE TABLE IF NOT EXISTS user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  assigned_event_ids UUID[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, role, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user
  ON user_roles(user_id);

-- Link registrations to authenticated users when the table already exists.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'registrations'
  ) THEN
    INSERT INTO users (id, email, password_hash, display_name)
    SELECT DISTINCT
      r.participant_id,
      'legacy+' || r.participant_id::text || '@we-event.test',
      '$2b$10$ZLvMEXurERIwVQwHCd78EOwF6NwZ6HY.TV24xG/AHtq0031vuC8G.',
      'Legacy Participant'
    FROM registrations r
    LEFT JOIN users u ON u.id = r.participant_id
    WHERE u.id IS NULL
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO user_roles (user_id, role)
    SELECT u.id, 'Participant'
    FROM users u
    LEFT JOIN user_roles ur
      ON ur.user_id = u.id AND ur.role = 'Participant' AND ur.organization_id IS NULL
    WHERE ur.id IS NULL
      AND u.email LIKE 'legacy+%@we-event.test'
    ON CONFLICT (user_id, role, organization_id) DO NOTHING;

    ALTER TABLE registrations
      DROP CONSTRAINT IF EXISTS fk_registrations_participant_user;
    ALTER TABLE registrations
      ADD CONSTRAINT fk_registrations_participant_user
      FOREIGN KEY (participant_id) REFERENCES users(id);
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
