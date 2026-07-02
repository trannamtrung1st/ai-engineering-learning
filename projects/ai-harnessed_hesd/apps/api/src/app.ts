import Fastify from "fastify";
import { createPostgresHealthProbe } from "./infra/db-probe.js";
import { registerHealthRoutes } from "./routes/health.js";

export async function buildApp() {
  const app = Fastify({ logger: false });
  const dbProbe = createPostgresHealthProbe(process.env.DATABASE_URL);
  await app.register(
    async (v1) => {
      registerHealthRoutes(v1, dbProbe);
    },
    { prefix: "/api/v1" },
  );
  return app;
}
