import { buildApp } from "./app.js";

const port = Number(process.env.PORT ?? process.env.API_PORT ?? 3001);

const app = await buildApp();

try {
  // Dual-stack so clients using "localhost" (::1 or 127.0.0.1) can connect.
  await app.listen({ port, host: "::" });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
