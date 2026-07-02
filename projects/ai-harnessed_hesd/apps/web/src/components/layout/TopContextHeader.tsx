import type { ReactNode } from "react";
import styles from "./TopContextHeader.module.css";

export interface TopContextHeaderProps {
  title: string;
  eyebrow?: string;
  badges?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}

export function TopContextHeader({
  title,
  eyebrow,
  badges,
  actions,
  meta,
}: TopContextHeaderProps) {
  return (
    <div className={styles.header}>
      <div className={styles.leading}>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <div className={styles.titleRow}>
          <h1 className={styles.title}>{title}</h1>
          {badges ? <div className={styles.badges}>{badges}</div> : null}
        </div>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </div>
  );
}
