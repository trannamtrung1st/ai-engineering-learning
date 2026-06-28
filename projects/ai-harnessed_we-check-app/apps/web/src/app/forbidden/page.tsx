import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { useRoleHome } from "@/hooks/use-role-home";

/** BR-08 / FR-12 — permission denied page at /forbidden */
export function ForbiddenRoutePage() {
  const homeTo = useRoleHome("/");

  return <ForbiddenPage homeTo={homeTo} />;
}
