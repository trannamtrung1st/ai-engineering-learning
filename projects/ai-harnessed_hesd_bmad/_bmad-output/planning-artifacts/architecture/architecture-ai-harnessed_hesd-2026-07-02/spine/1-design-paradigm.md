# 1. Design Paradigm

**Split-stack monorepo:** Next.js web (UI adapters + Supabase SSR auth + Realtime subscribe) and **NestJS API** (domain + REST). One repo, two deployable units. Business rules live only in `api/src/domain/`; web never mutates domain tables.

```mermaid
flowchart TB
  subgraph web["Web (Next.js)"]
    A[admin/*]
    I[instructor/*]
    S[student/*]
    MW[middleware.ts role + password gate]
  end
  subgraph api["API (NestJS)"]
    CTRL[controllers]
    subgraph domain["Domain (api/src/domain/)"]
      UC[use-cases]
      VAL[validation]
      GEO[geofence]
      TOK[session-tokens]
    end
    GUARD[AuthGuard + RolesGuard]
  end
  subgraph infra["Infrastructure"]
    DB[(Drizzle → Postgres)]
    AUTH[Supabase Auth JWT]
    RT[Supabase Realtime]
  end
  A -->|HTTP + JWT| CTRL
  I -->|HTTP + JWT| CTRL
  S -->|HTTP + JWT| CTRL
  MW --> A
  MW --> I
  MW --> S
  CTRL --> GUARD
  GUARD --> UC
  UC --> VAL
  UC --> GEO
  UC --> TOK
  UC --> DB
  GUARD --> AUTH
  I --> RT
  RT --> DB
```

**Dependency rule:** `web/` → HTTP → `api/` controllers → `api/src/domain/` → `api/src/infra/` → external SDKs. Domain never imports from `web/`. Web may read via RSC using Supabase client (RLS); domain writes only through API.
