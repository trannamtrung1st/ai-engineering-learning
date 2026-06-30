import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { usePermittedHubCards } from "@/hooks/use-permitted-nav";
import type { NavLayout } from "@/lib/permissions";
import { cn } from "@/lib/cn";

export interface NavCardProps {
  to: string;
  title: string;
  description?: string;
  icon: LucideIcon;
  testId: string;
}

/** Single hub quick-link card — min 44×44 px touch target */
export function NavCard({ to, title, description, icon: Icon, testId }: NavCardProps) {
  return (
    <Link
      to={to}
      className="group block min-h-touch rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
      data-testid={testId}
    >
      <Card className="h-full transition-shadow group-hover:shadow-md">
        <CardContent className="flex flex-col gap-3 p-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary-50 text-primary-700">
            <Icon className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <h2 className="font-display text-h3 font-semibold text-text-primary">{title}</h2>
            {description ? (
              <p className="mt-1 text-body text-text-secondary">{description}</p>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

export interface QuickActionGridProps {
  children: React.ReactNode;
  variant?: NavLayout;
}

/** Responsive hub card grid — 1 col mobile, 2 md+, 3 admin lg+ */
export function QuickActionGrid({ children, variant = "admin" }: QuickActionGridProps) {
  return (
    <div
      className={cn(
        "grid gap-4",
        variant === "admin" ? "sm:grid-cols-2 xl:grid-cols-3" : "sm:grid-cols-2",
      )}
      data-testid="role-home-hub-grid"
    >
      {children}
    </div>
  );
}

export interface RoleHomeHubProps {
  variant: NavLayout;
  title?: string;
  description?: string;
  icons: Record<string, LucideIcon>;
  className?: string;
}

/** FR-18 / BR-14 — permission-filtered role home quick links */
export function RoleHomeHub({
  variant,
  title,
  description,
  icons,
  className,
}: RoleHomeHubProps) {
  const cards = usePermittedHubCards(variant);

  if (cards.length === 0) {
    return null;
  }

  return (
    <section className={cn("mb-6", className)} data-testid="role-home-hub">
      {title ? (
        <header className="mb-4">
          <h2 className="font-display text-h2 font-semibold text-text-primary">{title}</h2>
          {description ? (
            <p className="mt-1 text-body text-text-secondary">{description}</p>
          ) : null}
        </header>
      ) : null}
      <QuickActionGrid variant={variant}>
        {cards.map((card) => {
          const Icon = icons[card.to] ?? icons[card.testId];
          if (!Icon) {
            return null;
          }
          return (
            <NavCard
              key={card.to}
              to={card.to}
              title={card.title}
              description={card.description}
              icon={Icon}
              testId={card.testId}
            />
          );
        })}
      </QuickActionGrid>
    </section>
  );
}
