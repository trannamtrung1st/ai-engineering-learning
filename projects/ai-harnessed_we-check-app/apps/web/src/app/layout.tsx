import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { ErrorBoundary } from "@/components/layout/error-boundary";
import { appCopy } from "@/lib/copy/status-labels";

export interface RootLayoutProps {
  children?: ReactNode;
}

/** Root shell — providers, skip link, error boundary. No role navigation chrome. */
export function RootLayout({ children }: RootLayoutProps) {
  return (
    <ErrorBoundary>
      <a href="#main-content" className="skip-link">
        {appCopy.skipToContent}
      </a>
      {children ?? <Outlet />}
      <Toaster
        position="top-center"
        richColors
        closeButton
        duration={5000}
        toastOptions={{ classNames: { toast: "app-toast" } }}
      />
    </ErrorBoundary>
  );
}
