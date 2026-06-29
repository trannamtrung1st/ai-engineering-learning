import { NotFoundPage } from "@/components/layout/not-found-page";
import { useRoleHome } from "@/hooks/use-role-home";

/** Catch-all not-found route with role-aware home link */
export function NotFoundRoutePage() {
  const homeTo = useRoleHome("/");

  return (
    <main id="main-content" className="mx-auto max-w-[720px] px-4 py-8">
      <NotFoundPage homeTo={homeTo} />
    </main>
  );
}
