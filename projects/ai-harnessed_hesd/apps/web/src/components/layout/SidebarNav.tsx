import { NavLink } from "react-router-dom";
import { LogoutControl } from "./LogoutControl";
import styles from "./SidebarNav.module.css";

export interface SidebarNavItem {
  to: string;
  label: string;
}

export interface SidebarNavProps {
  items: SidebarNavItem[];
  brand?: string;
  showLogout?: boolean;
}

export function SidebarNav({ items, brand = "Attendly", showLogout = true }: SidebarNavProps) {
  return (
    <nav className={styles.nav} aria-label="Điều hướng vai trò">
      <p className={styles.brand}>{brand}</p>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                [styles.link, isActive ? styles.active : ""].filter(Boolean).join(" ")
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
      {showLogout ? (
        <div className={styles.footer}>
          <div className={styles.separator} role="separator" />
          <LogoutControl className={styles.logout} />
        </div>
      ) : null}
    </nav>
  );
}
