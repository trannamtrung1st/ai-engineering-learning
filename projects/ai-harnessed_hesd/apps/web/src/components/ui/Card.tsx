import type { ReactNode } from "react";
import styles from "./Card.module.css";

export interface CardProps {
  children: ReactNode;
  className?: string;
  elevated?: boolean;
}

export function Card({ children, className, elevated = true }: CardProps) {
  const classes = [styles.card, elevated ? styles.elevated : "", className ?? ""]
    .filter(Boolean)
    .join(" ");

  return <section className={classes}>{children}</section>;
}
