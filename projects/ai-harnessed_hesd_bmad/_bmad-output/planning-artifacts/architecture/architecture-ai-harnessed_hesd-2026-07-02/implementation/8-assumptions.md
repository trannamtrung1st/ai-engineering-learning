# 8. Assumptions

Confirm or override when scaffolding:

| ID | Assumption | Revisit when |
| --- | --- | --- |
| A-ARCH-1 | Repo folder name `hesd-attendance` | First commit — adjust path if preferred |
| A-ARCH-2 | Display timezone `Asia/Ho_Chi_Minh` for pilot UI | First date/time component |
| A-ARCH-3 | Instructor QR display poll interval 5s (token TTL stays 30s per spec) | QR display implementation |
| A-ARCH-4 | `@supabase/*` packages pinned to latest stable at scaffold time | `package.json` creation |
| A-ARCH-5 | API listens on port `3001`; web on `3000` | `docker-compose.yml` / `api/.env` |
| A-ARCH-6 | NestJS global prefix `/api/v1` | `api/src/main.ts` bootstrap |
