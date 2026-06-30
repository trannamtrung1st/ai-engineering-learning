import type { LucideIcon } from "lucide-react";
import { NavLink } from "@/components/shared/navigation/nav-link";
import { usePermittedNav } from "@/hooks/use-permitted-nav";
import type { NavLayout } from "@/lib/permissions";
import { cn } from "@/lib/cn";

export interface SidebarNavProps {
  layout: NavLayout;
  icons: Record<string, LucideIcon>;
  header?: React.ReactNode;
  onNavigate?: () => void;
  testId?: string;
  className?: string;
}

/** FR-18 / BR-14 — permission-filtered sidebar navigation */
export function SidebarNav({
  layout,
  icons,
  header,
  onNavigate,
  testId,
  className,
}: SidebarNavProps) {
  const items = usePermittedNav(layout);

  return (
    <div className={cn("flex h-full flex-col pl-1", className)}>
      {header}
      <nav
        className="flex flex-col gap-1 p-4 pl-5"
        data-testid={testId ?? `${layout}-sidebar`}
        aria-label={
          layout === "admin"
            ? "Điều hướng quản trị"
            : "Điều hướng giảng viên"
        }
      >
        {items.map((item) => {
          const Icon = icons[item.to];
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/admin"}
              className={cn("w-full rounded-md")}
              {...(onNavigate ? { onClick: onNavigate } : {})}
            >
              {Icon ? <Icon className="h-5 w-5" aria-hidden="true" /> : null}
              {item.label}
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}
