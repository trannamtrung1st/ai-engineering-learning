import { NavLink as RouterNavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

export interface NavLinkProps {
  to: string;
  children: React.ReactNode;
  end?: boolean;
  className?: string;
  onClick?: () => void;
}

export function NavLink({ to, children, end, className, onClick }: NavLinkProps) {
  return (
    <RouterNavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "flex min-h-touch items-center gap-2 rounded-md px-3 py-2 text-body font-medium text-text-primary transition-colors",
          isActive && "bg-primary-50 text-primary-700",
          className,
        )
      }
    >
      {children}
    </RouterNavLink>
  );
}
