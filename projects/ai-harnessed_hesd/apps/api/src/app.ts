import Fastify from "fastify";
import { createPostgresHealthProbe } from "./infra/db-probe.js";
import { registerAcademicStructureModule } from "./modules/academic-structure/index.js";
import { registerIdentityModule } from "./modules/identity/index.js";
import { registerSessionLifecycleModule } from "./modules/session-lifecycle/index.js";
import { registerHealthRoutes } from "./routes/health.js";

export async function buildApp() {
  const app = Fastify({ logger: false });
  const dbProbe = createPostgresHealthProbe(process.env.DATABASE_URL);
  const connectionString = process.env.DATABASE_URL;
  let pool: Awaited<ReturnType<typeof registerIdentityModule>> = null;

  await app.register(
    async (v1) => {
      registerHealthRoutes(v1, dbProbe);
      pool = await registerIdentityModule(v1, { connectionString });
      await registerAcademicStructureModule(v1, { connectionString, pool: pool ?? undefined });
      await registerSessionLifecycleModule(v1, { connectionString, pool: pool ?? undefined });
    },
    { prefix: "/api/v1" },
  );
  return app;
}
