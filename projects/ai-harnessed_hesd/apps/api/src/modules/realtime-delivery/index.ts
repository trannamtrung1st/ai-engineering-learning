import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createRealtimeDeliveryRepository } from "./repository.js";
import { registerRealtimeDeliveryRoutes } from "./routes.js";

export interface RealtimeDeliveryModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerRealtimeDeliveryModule(
  app: FastifyInstance,
  options: RealtimeDeliveryModuleOptions = {},
): Promise<ReturnType<typeof createRealtimeDeliveryRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createRealtimeDeliveryRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerRealtimeDeliveryRoutes(app, identityServices, repository);
  return repository;
}

export {
  createRealtimeDeliveryRepository,
  getOperationalTelemetrySnapshot,
  recordCheckInAttemptTelemetry,
  recordQrTokenIssuedTelemetry,
  recordSessionLifecycleTelemetry,
} from "./repository.js";
export { realtimeDeliveryGateway } from "./event-gateway.js";
export type { RealtimeDeliveryRepository } from "./repository.js";
export type {
  OperationalTelemetryEvent,
  RealtimeRosterEvent,
  RosterUpdateReason,
} from "./types.js";
