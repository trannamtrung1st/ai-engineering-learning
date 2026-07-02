# Ephemeral integration/e2e stack — separate from preview dev DB (docker-compose.yml).
# Start: npm run aih:test:stack:reset
name: {{PRODUCT_SLUG}}-test

services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${TEST_POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${TEST_POSTGRES_PASSWORD:-postgres}
      POSTGRES_DB: ${TEST_POSTGRES_DB:-app_test}
    ports:
      - "${TEST_POSTGRES_PORT:-5433}:5432"
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "pg_isready -U ${TEST_POSTGRES_USER:-postgres} -d ${TEST_POSTGRES_DB:-app_test}",
        ]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 5s
