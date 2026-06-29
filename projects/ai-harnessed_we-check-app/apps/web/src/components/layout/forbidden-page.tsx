import { ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/ui/empty-state";
import { appCopy } from "@/lib/copy/status-labels";
import { cn } from "@/lib/cn";

export interface ForbiddenPageProps {
  homeTo?: string;
}

export function ForbiddenPage({ homeTo = "/" }: ForbiddenPageProps) {
  return (
    <EmptyState
      icon={ShieldAlert}
      title={appCopy.forbiddenTitle}
      description={appCopy.forbiddenMessage}
      action={
        <Link
          to={homeTo}
          className={cn(
            "inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700",
          )}
        >
          {appCopy.forbiddenHome}
        </Link>
      }
    />
  );
}
