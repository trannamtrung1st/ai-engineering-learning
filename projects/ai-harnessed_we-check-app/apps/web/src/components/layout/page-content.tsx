import { cn } from "@/lib/cn";

const variantClasses = {
  narrow: "max-w-[480px]",
  default: "max-w-[720px]",
  wide: "max-w-[1280px]",
} as const;

export type PageContentVariant = keyof typeof variantClasses;

export interface PageContentProps {
  children: React.ReactNode;
  variant?: PageContentVariant;
  className?: string;
}

export function PageContent({
  children,
  variant = "default",
  className,
}: PageContentProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-4 py-6 md:px-6",
        variantClasses[variant],
        className,
      )}
    >
      {children}
    </div>
  );
}
