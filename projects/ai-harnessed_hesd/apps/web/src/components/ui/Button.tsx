import type { ButtonHTMLAttributes } from "react";
import styles from "./Button.module.css";

export type ButtonVariant =
  | "brand"
  | "secondary"
  | "tertiary"
  | "success"
  | "danger"
  | "warning"
  | "dark"
  | "ghost";

export type ButtonSize = "xs" | "sm" | "base" | "lg" | "xl";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
}

export function Button({
  variant = "brand",
  size = "base",
  fullWidth = false,
  className,
  type = "button",
  ...props
}: ButtonProps) {
  const classes = [
    styles.button,
    styles[`variant-${variant}`],
    styles[`size-${size}`],
    fullWidth ? styles.fullWidth : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return <button type={type} className={classes} {...props} />;
}
