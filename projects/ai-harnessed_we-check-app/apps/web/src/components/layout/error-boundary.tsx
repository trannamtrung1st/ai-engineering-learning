import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { appCopy } from "@/lib/copy/status-labels";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Root layout error:", error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
          <h1 className="text-h1 font-semibold">{appCopy.errorBoundaryTitle}</h1>
          <p className="max-w-md text-body text-text-secondary">
            {appCopy.errorBoundaryMessage}
          </p>
          <Button type="button" onClick={() => window.location.reload()}>
            {appCopy.errorBoundaryReload}
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
