import Fastify from "fastify";
import { createPostgresHealthProbe } from "./infra/db-probe.js";
import { registerIdentityModule } from "./modules/identity/index.js";
import { registerHealthRoutes } from "./routes/health.js";

export async function buildApp() {
  const app = Fastify({ logger: false });
  const dbProbe = createPostgresHealthProbe(process.env.DATABASE_URL);
  await app.register(
    async (v1) => {
      registerHealthRoutes(v1, dbProbe);
      await registerIdentityModule(v1, { connectionString: process.env.DATABASE_URL });
    },
    { prefix: "/api/v1" },
  );
  return app;
}
