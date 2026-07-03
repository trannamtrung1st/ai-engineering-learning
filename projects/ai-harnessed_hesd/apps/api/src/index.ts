import { buildApp } from "./app.js";

const port = Number(process.env.PORT ?? process.env.API_PORT ?? 3001);

const app = await buildApp();

try {
  await app.listen({ port, host: "0.0.0.0" });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
