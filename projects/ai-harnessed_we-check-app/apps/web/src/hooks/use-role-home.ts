import { useEffect, useState } from "react";
import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";
import { fetchAuthUser } from "@/lib/auth-session";
import { getRoleHome } from "@/lib/auth-redirect";

/** Resolve role home for error pages — uses authenticated role when available */
export function useRoleHome(fallback = "/"): string {
  const [homeTo, setHomeTo] = useState(fallback);

  useEffect(() => {
    void fetchAuthUser().then((result) => {
      if (result.ok) {
        setHomeTo(getRoleHome(result.user.role));
      }
    });
  }, [fallback]);

  return homeTo;
}

export { UserRole, type UserRoleType };
