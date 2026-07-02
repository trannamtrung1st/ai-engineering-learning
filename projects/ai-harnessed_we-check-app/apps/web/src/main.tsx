import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppProviders } from "@/app/providers";
import { AppRouter } from "@/app/router";
import { getCachedAuthUser } from "@/lib/auth-session";
import "@/styles/globals.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root not found");
}

const bootAuthUser = getCachedAuthUser();

createRoot(root).render(
  <StrictMode>
    <AppProviders bootAuthUser={bootAuthUser}>
      <AppRouter />
    </AppProviders>
  </StrictMode>,
);
