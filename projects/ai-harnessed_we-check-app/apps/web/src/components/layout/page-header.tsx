import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

export interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  backTo?: string;
  className?: string;
}

export function PageHeader({
  title,
  description,
  actions,
  backTo,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn("mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between", className)}>
      <div className="flex flex-col gap-2">
        {backTo ? (
          <Link
            to={backTo}
            className="inline-flex min-h-touch items-center gap-2 text-small text-text-secondary hover:text-primary-700"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Quay lại
          </Link>
        ) : null}
        <div>
          <h1 className="text-h1 font-semibold text-text-primary">{title}</h1>
          {description ? (
            <p className="mt-1 text-body text-text-secondary">{description}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
