import type { FastifyInstance } from "fastify";
import { sendApiSuccess } from "./http.js";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "./middleware.js";

/** Auth-guarded route stubs — business handlers ship in downstream modules. */
export async function registerProtectedRouteStubs(
  app: FastifyInstance,
  services: IdentityServices,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardAuditRead = createAuthorizeGuard(services, {
    resource: "AuditLog",
    action: "read",
  });

  const emptyList = { items: [], pagination: { page: 1, pageSize: 25, totalItems: 0, totalPages: 0 } };

  app.get(
    "/audit-logs",
    { preHandler: combineGuards(authenticate, guardAuditRead) },
    async (request, reply) => {
      sendApiSuccess(reply, request, 200, emptyList);
    },
  );

}
