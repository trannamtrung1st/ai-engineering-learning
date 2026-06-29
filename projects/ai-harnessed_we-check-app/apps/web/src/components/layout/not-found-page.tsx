import { FileQuestion } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/ui/empty-state";
import { appCopy } from "@/lib/copy/status-labels";
import { cn } from "@/lib/cn";

export interface NotFoundPageProps {
  homeTo?: string;
}

export function NotFoundPage({ homeTo = "/" }: NotFoundPageProps) {
  return (
    <EmptyState
      icon={FileQuestion}
      title={appCopy.notFoundTitle}
      description={appCopy.notFoundMessage}
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
