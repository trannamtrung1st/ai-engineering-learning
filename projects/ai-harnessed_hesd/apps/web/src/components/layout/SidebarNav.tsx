import { NavLink } from "react-router-dom";
import styles from "./SidebarNav.module.css";

export interface SidebarNavItem {
  to: string;
  label: string;
}

export interface SidebarNavProps {
  items: SidebarNavItem[];
  brand?: string;
}

export function SidebarNav({ items, brand = "Attendly" }: SidebarNavProps) {
  return (
    <nav className={styles.nav}>
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
    </nav>
  );
}
