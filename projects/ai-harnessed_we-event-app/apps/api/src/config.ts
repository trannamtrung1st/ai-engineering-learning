export interface AppConfig {
  port: number;
  databaseUrl: string;
  jwtSecret: string;
  timezone: string;
  devAuthEnabled: boolean;
  seedEnabled: boolean;
  uploadsDir: string;
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

export function loadConfig(): AppConfig {
  const port = Number(process.env.PORT ?? "3001");
  if (!Number.isInteger(port) || port <= 0) {
    throw new Error("PORT must be a positive integer");
  }

  return {
    port,
    databaseUrl: requireEnv("DATABASE_URL"),
    jwtSecret: requireEnv("JWT_SECRET"),
    timezone: process.env.TIMEZONE ?? "UTC",
    devAuthEnabled: process.env.DEV_AUTH_ENABLED === "true",
    seedEnabled: process.env.SEED_ENABLED === "true",
    uploadsDir: process.env.UPLOADS_DIR ?? "./uploads",
  };
}
