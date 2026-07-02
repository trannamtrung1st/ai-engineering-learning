# 9. Structural Seed

## Deployment topology

```mermaid
flowchart LR
  subgraph host["Developer host"]
    WEB[Next.js web<br/>npm run dev :3000]
  end
  subgraph compose["Docker Compose"]
    PG[(Postgres 16)]
    API[NestJS API :3001]
  end
  subgraph supa["Supabase local or hosted"]
    AUTH[Auth]
    RT[Realtime]
  end
  subgraph prod["Production (partial)"]
    VERCEL[Vercel web]
    SUPA_HOST[Supabase hosted]
  end
  STUDENT[Student mobile browser]
  INSTRUCTOR[Instructor laptop]
  ADMIN[Admin browser]
  STUDENT --> WEB
  INSTRUCTOR --> WEB
  ADMIN --> WEB
  WEB -->|REST + JWT| API
  WEB --> AUTH
  INSTRUCTOR --> RT
  API --> PG
  RT --> SUPA_HOST
  WEB --> VERCEL
  VERCEL --> SUPA_HOST
```

## Core entity model

```mermaid
erDiagram
  profiles ||--o{ workshop_sessions : "instructor creates"
  profiles ||--o{ attendance_records : "student"
  cohort_rosters ||--o{ roster_members : contains
  profiles ||--o{ roster_members : "student_id"
  workshop_sessions }o--|| cohort_rosters : binds
  workshop_sessions ||--o{ session_tokens : mints
  workshop_sessions ||--o{ attendance_records : tracks
  workshop_sessions ||--o{ check_in_attempts : logs
  profiles ||--o{ check_in_attempts : "attempted by"
```

Key columns (seed — code owns detail):

| Table | Purpose |
| --- | --- |
| `profiles` | `id` (= auth.users.id), `role`, `student_id?`, `full_name`, `must_change_password` |
| `cohort_rosters` | Named roster for session binding |
| `roster_members` | `(roster_id, student_id)` membership |
| `workshop_sessions` | `title`, `scheduled_at`, `status`, `roster_id`, `geofence_lat/lng`, `radius_m`, `instructor_id` |
| `session_tokens` | `session_id`, `token`, `expires_at` |
| `attendance_records` | `session_id`, `student_id`, `status`, `checked_in_at`, `source` |
| `check_in_attempts` | Append-only audit of all attempts |

## Source tree

```text
hesd-attendance/                    # repo root
  app/                              # Next.js web (AD-7 role routes)
    (admin)/
    (instructor)/
    (student)/
    auth/
  api/                              # NestJS API (AD-15)
    src/
      domain/
        check-in/execute-check-in.ts   # AD-5 orchestrator
        check-in/mint-session-token.ts
        check-in/geofence.ts           # AD-10 haversine
        accounts/
        rosters/
        sessions/
        attendance/manual-override.ts
        export/csv-export.ts
      infra/
        db/schema.ts                   # Drizzle schema
        db/client.ts
      modules/                         # NestJS modules → controllers
      guards/                          # AuthGuard, RolesGuard
    drizzle.config.ts
  lib/supabase/                       # web-only Supabase clients
  components/
  middleware.ts
  supabase/
    migrations/                       # drizzle-kit output
    seed.sql                          # AD-12 bootstrap admin
  docker-compose.yml                  # AD-14 profiles local + integration
  .env / .env.local
```

## Check-in sequence

```mermaid
sequenceDiagram
  participant S as Student browser
  participant W as Next.js web
  participant API as NestJS POST /check-in
  participant D as executeCheckIn()
  participant DB as Postgres

  S->>W: submit check-in form
  W->>API: token, sessionId, lat, lng + JWT
  API->>D: invoke (authenticated)
  D->>DB: BEGIN
  D->>D: checks 1-5
  alt pass
    D->>DB: INSERT attendance_records
    D->>DB: INSERT check_in_attempts (success)
    D->>DB: COMMIT
    DB-->>S: Realtime push to instructor
  else fail
    D->>DB: INSERT check_in_attempts (failure)
    D->>DB: COMMIT
    API-->>W: rejection + reason
    W-->>S: show error
  end
```
