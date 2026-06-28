const DEFAULT_DATABASE_URL =
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

export interface ApiEnv {
  nodeEnv: string;
  port: number;
  databaseUrl: string;
  corsOrigin: string;
  logLevel: string;
}

export function loadEnv(): ApiEnv {
  return {
    nodeEnv: process.env.NODE_ENV ?? "development",
    port: Number(process.env.PORT ?? process.env.API_PORT ?? 3001),
    databaseUrl: process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL,
    corsOrigin: process.env.CORS_ORIGIN ?? "http://localhost:3000",
    logLevel: process.env.LOG_LEVEL ?? "info",
  };
}
