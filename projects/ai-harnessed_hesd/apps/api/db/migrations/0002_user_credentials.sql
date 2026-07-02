-- Identity credentials for local and test login (FR-15, FR-36)

CREATE TABLE user_credentials (
  user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  password_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
