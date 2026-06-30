import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { useRoleHome } from "@/hooks/use-role-home";
import { reportCopy } from "@/lib/copy/report-labels";
import { useSearchParams } from "react-router-dom";

/** BR-08 / FR-12 — permission denied page at /forbidden */
export function ForbiddenRoutePage() {
  const homeTo = useRoleHome("/");
  const [searchParams] = useSearchParams();
  const description =
    searchParams.get("reason") === "report" ? reportCopy.reportAccessDenied : undefined;

  return <ForbiddenPage homeTo={homeTo} description={description} />;
}
