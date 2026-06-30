import { Outlet } from "react-router-dom";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { appCopy } from "@/lib/copy/status-labels";

export function AuthLayout() {
  return (
    <div
      className="flex min-h-screen bg-surface"
      data-testid="auth-layout"
    >
      <aside
        className="relative hidden w-1/2 flex-col justify-center bg-gradient-to-br from-brand-700 to-brand-900 p-10 lg:p-12 md:flex"
        aria-label="We Check"
      >
        <div className="absolute inset-y-0 left-0 w-1 bg-brand-500/40" aria-hidden="true" />
        <h1 className="font-display text-display font-bold text-text-inverse">
          {appCopy.productName}
        </h1>
        <p className="mt-3 max-w-md text-body text-brand-100">{appCopy.productSubtitle}</p>
        <p className="mt-8 text-small text-brand-100/80">
          Điểm danh nhanh, minh bạch và đáng tin cậy cho buổi học tại trường.
        </p>
      </aside>

      <div className="flex w-full flex-1 items-center justify-center px-4 py-8 md:w-1/2">
        <Card className="w-full max-w-[400px] shadow-lg motion-safe:hover:shadow-lg">
          <CardHeader className="flex-col items-start gap-1 pb-0 md:hidden">
            <h1 className="font-display text-h1 font-semibold text-brand-700">
              {appCopy.productName}
            </h1>
            <p className="text-body text-text-secondary">{appCopy.productSubtitle}</p>
          </CardHeader>
          <CardContent className="md:pt-6">
            <Outlet />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
