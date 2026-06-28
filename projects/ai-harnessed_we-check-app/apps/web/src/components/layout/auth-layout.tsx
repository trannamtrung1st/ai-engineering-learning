import { Outlet } from "react-router-dom";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { appCopy } from "@/lib/copy/status-labels";

export function AuthLayout() {
  return (
    <div
      className="flex min-h-screen items-center justify-center bg-surface px-4 py-8"
      data-testid="auth-layout"
    >
      <Card className="w-full max-w-[400px]">
        <CardHeader className="flex-col items-start gap-1 pb-0">
          <h1 className="text-h1 font-semibold text-primary-700">
            {appCopy.productName}
          </h1>
          <p className="text-body text-text-secondary">{appCopy.productSubtitle}</p>
        </CardHeader>
        <CardContent>
          <Outlet />
        </CardContent>
      </Card>
    </div>
  );
}
