import * as LabelPrimitive from "@radix-ui/react-label";
import { cn } from "@/lib/cn";

export interface LabelProps
  extends React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root> {
  required?: boolean;
}

export function Label({ className, required, children, ...props }: LabelProps) {
  return (
    <LabelPrimitive.Root
      className={cn("text-small font-medium text-text-primary", className)}
      {...props}
    >
      {children}
      {required ? (
        <span className="text-danger-500" aria-hidden="true">
          {" "}
          *
        </span>
      ) : null}
    </LabelPrimitive.Root>
  );
}
