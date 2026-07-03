import { Link, Outlet, useLocation } from "react-router-dom";
import { LogoutControl } from "../components/layout/LogoutControl";
import { isStudentAuthenticated } from "../lib/auth/auth-gate";
import styles from "./StudentLayout.module.css";

export function StudentLayout() {
  const { pathname } = useLocation();
  const onLogin = pathname === "/login";
  const showShellHeader = !onLogin && isStudentAuthenticated();

  if (!showShellHeader) {
    return <Outlet />;
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link className={styles.homeLink} to="/check-in">
          Trang chủ
        </Link>
        <LogoutControl size="base" className={styles.logout} />
      </header>
      <Outlet />
    </div>
  );
}
