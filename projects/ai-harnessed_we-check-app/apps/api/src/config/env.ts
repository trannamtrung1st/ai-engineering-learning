const DEFAULT_DATABASE_URL =
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

export interface ApiEnv {
  nodeEnv: string;
  port: number;
  databaseUrl: string;
  corsOrigin: string;
  logLevel: string;
  seedEnabled: boolean;
}

export function loadEnv(): ApiEnv {
  const seedRaw = process.env.SEED_ENABLED;
  const seedEnabled =
    seedRaw === undefined ? false : seedRaw === "true" || seedRaw === "1";

  return {
    nodeEnv: process.env.NODE_ENV ?? "development",
    port: Number(process.env.PORT ?? process.env.API_PORT ?? 3001),
    databaseUrl: process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL,
    corsOrigin: process.env.CORS_ORIGIN ?? "http://localhost:3007",
    logLevel: process.env.LOG_LEVEL ?? "info",
    seedEnabled,
  };
}
