"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { Alert } from "@/components/ui/alert";
import { cn } from "@/lib/cn";

export type ToastVariant = "info" | "success" | "warning" | "error";

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  variant?: ToastVariant;
}

interface ToastRegionProps {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
  className?: string;
}

export function ToastRegion({ toasts, onDismiss, className }: ToastRegionProps) {
  return (
    <div
      className={cn(
        "pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2",
        className,
      )}
      aria-live="polite"
      aria-relevant="additions"
    >
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <Alert
            variant={toast.variant ?? "info"}
            title={toast.title}
            action={
              <button
                type="button"
                className="text-[length:var(--font-size-xs)] font-[var(--font-weight-medium)] text-[var(--color-text-secondary)] underline-offset-2 hover:underline"
                onClick={() => onDismiss(toast.id)}
              >
                Dismiss
              </button>
            }
          >
            {toast.description}
          </Alert>
        </div>
      ))}
    </div>
  );
}

interface ToastContextValue {
  push: (toast: Omit<ToastMessage, "id">) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

function useToasts() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const dismiss = (id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  };

  const push = (toast: Omit<ToastMessage, "id">) => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { ...toast, id }]);
    return id;
  };

  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts.map((toast) =>
      window.setTimeout(() => dismiss(toast.id), 5000),
    );
    return () => timers.forEach(clearTimeout);
  }, [toasts]);

  return { toasts, push, dismiss };
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const { toasts, push, dismiss } = useToasts();

  return (
    <ToastContext.Provider value={{ push, dismiss }}>
      {children}
      <ToastRegion toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
}
