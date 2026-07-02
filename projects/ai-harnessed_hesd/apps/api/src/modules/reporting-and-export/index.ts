import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createReportingRepository } from "./repository.js";
import { registerReportingRoutes } from "./routes.js";

export interface ReportingModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerReportingModule(
  app: FastifyInstance,
  options: ReportingModuleOptions = {},
): Promise<ReturnType<typeof createReportingRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createReportingRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerReportingRoutes(app, identityServices, repository);
  return repository;
}

export { createReportingRepository } from "./repository.js";
export type { ReportingRepository } from "./repository.js";
export { resolveReportExportScope } from "./scope.js";
export { parseReportQuery, validateExportBody } from "./validation.js";
export type {
  AttendanceReportFilters,
  AttendanceReportRow,
  ExportJobResult,
  ResolvedReportScope,
} from "./types.js";
