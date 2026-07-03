import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const port = Number(process.env.PORT ?? process.env.WEB_PORT ?? 3007);

export default defineConfig({
  plugins: [react()],
  server: {
    port,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:3001",
        changeOrigin: true,
      },
    },
  },
  preview: {
    port,
    strictPort: true,
  },
});
