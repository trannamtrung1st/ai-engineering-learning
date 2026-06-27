import type { ReactNode } from "react";

import { AuthChrome } from "@/components/auth/auth-chrome";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return <AuthChrome>{children}</AuthChrome>;
}
