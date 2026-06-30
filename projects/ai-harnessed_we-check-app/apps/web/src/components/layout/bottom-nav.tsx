import type { LucideIcon } from "lucide-react";
import { NavLink } from "@/components/shared/navigation/nav-link";
import { usePermittedNav } from "@/hooks/use-permitted-nav";

export interface BottomNavProps {
  icons: Record<string, LucideIcon>;
}

/** FR-18 / BR-14 — permission-filtered student bottom navigation */
export function BottomNav({ icons }: BottomNavProps) {
  const items = usePermittedNav("student");

  return (
    <nav
      aria-label="Điều hướng sinh viên"
      className="sticky bottom-0 border-t border-border bg-surface-raised/95 pb-[env(safe-area-inset-bottom)] shadow-sm backdrop-blur-sm"
      data-testid="student-bottom-nav"
    >
      <div className="mx-auto flex max-w-[480px] justify-around px-2 py-1">
        {items.map((item) => {
          const Icon = icons[item.to];
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className="flex-1 flex-col gap-1 rounded-full py-2 text-small"
            >
              {Icon ? <Icon className="h-5 w-5" aria-hidden="true" /> : null}
              {item.label}
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
