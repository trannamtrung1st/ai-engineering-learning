import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "./middleware.js";

/** Auth-guarded route stubs — business handlers ship in downstream modules. */
export async function registerProtectedRouteStubs(
  _app: FastifyInstance,
  _services: IdentityServices,
): Promise<void> {
  // Audit logs are registered by M08 audit-and-compliance module.
}
