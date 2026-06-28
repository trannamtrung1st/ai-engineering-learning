import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.WEB_PORT) || 3000,
    proxy: {
      "/api/v1": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:3001",
        changeOrigin: true,
      },
    },
  },
});
