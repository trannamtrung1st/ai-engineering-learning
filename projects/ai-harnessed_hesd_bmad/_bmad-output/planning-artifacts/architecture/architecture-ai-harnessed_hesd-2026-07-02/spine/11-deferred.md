# 11. Deferred

| Item | Why deferred |
| --- | --- |
| Production API hosting (Railway, Fly, ECS, etc.) | Local + integration compose sufficient for build phase; pick when deploying pilot API |
| CI/CD pipeline details | Solo pilot; Vercel git deploy for web sufficient for now |
| Observability / APM / error tracking | Basic console logs enough for internal pilot |
| Rate limiting / WAF | Pilot scale (150/10min) handled by platform defaults; revisit if abused |
| Offline / PWA | Mobile web online-only for MVP |
| Email notifications | No FR requires email in MVP |
| Multi-workshop tenancy / org model | Single HESD pilot org implied |
| Automated E2E test stack (Playwright) | User deferred; pick when first E2E story starts |
| Integration test framework choice (Jest vs Vitest in api/) | Pick when first integration test story; compose profile ready |
| i18n beyond Vietnamese copy in UI strings | English docs; UI copy can mix per UX spine |
| Shared `packages/` types between web and api | Duplicate zod schemas until duplication hurts |
