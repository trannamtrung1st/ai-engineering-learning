import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createCheckInRepository } from "./repository.js";
import { registerCheckInRoutes } from "./routes.js";

export interface CheckInModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerCheckInModule(
  app: FastifyInstance,
  options: CheckInModuleOptions = {},
): Promise<ReturnType<typeof createCheckInRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createCheckInRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerCheckInRoutes(app, identityServices, repository);
  return repository;
}

export { createCheckInRepository } from "./repository.js";
export type { CheckInRepository } from "./repository.js";
export { evaluateCheckInFailure, resolveAttendanceStatus } from "./validation.js";
export { QR_TTL_MS, hashQrToken, issueQrToken } from "./qr-service.js";
