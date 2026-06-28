import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

export interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  return (
    <nav aria-label="Đường dẫn" className={cn("flex items-center gap-1 text-small", className)}>
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <span key={`${item.label}-${index}`} className="inline-flex items-center gap-1">
            {index > 0 ? (
              <ChevronRight className="h-4 w-4 text-text-secondary" aria-hidden="true" />
            ) : null}
            {item.to && !isLast ? (
              <Link
                to={item.to}
                className="text-text-secondary hover:text-primary-700"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={isLast ? "font-medium text-text-primary" : "text-text-secondary"}
                aria-current={isLast ? "page" : undefined}
              >
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
