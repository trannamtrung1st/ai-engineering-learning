import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "var(--color-brand-50)",
          100: "var(--color-brand-100)",
          500: "var(--color-brand-500)",
          700: "var(--color-brand-700)",
          900: "var(--color-brand-900)",
        },
        primary: {
          50: "var(--color-primary-50)",
          100: "var(--color-primary-100)",
          500: "var(--color-primary-500)",
          600: "var(--color-primary-600)",
          700: "var(--color-primary-700)",
          foreground: "var(--color-primary-foreground)",
        },
        surface: {
          DEFAULT: "var(--color-surface-default)",
          raised: "var(--color-surface-raised)",
          muted: "var(--color-surface-muted)",
          inverse: "var(--color-surface-inverse)",
        },
        text: {
          primary: "var(--color-text-primary)",
          secondary: "var(--color-text-secondary)",
          inverse: "var(--color-text-inverse)",
          disabled: "var(--color-text-disabled)",
        },
        border: {
          DEFAULT: "var(--color-border-default)",
          strong: "var(--color-border-strong)",
        },
        success: {
          50: "var(--color-success-50)",
          500: "var(--color-success-500)",
        },
        warning: {
          50: "var(--color-warning-50)",
          500: "var(--color-warning-500)",
        },
        danger: {
          50: "var(--color-danger-50)",
          500: "var(--color-danger-500)",
        },
        info: {
          50: "var(--color-info-50)",
          500: "var(--color-info-500)",
        },
        qr: {
          bg: "var(--color-qr-bg)",
          fg: "var(--color-qr-fg)",
          countdown: "var(--color-qr-countdown)",
          accent: "var(--color-qr-accent)",
          warning: "var(--color-qr-warning)",
        },
      },
      spacing: {
        0: "var(--space-0)",
        1: "var(--space-1)",
        2: "var(--space-2)",
        3: "var(--space-3)",
        4: "var(--space-4)",
        5: "var(--space-5)",
        6: "var(--space-6)",
        8: "var(--space-8)",
        10: "var(--space-10)",
        12: "var(--space-12)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        full: "var(--radius-full)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        brand: "var(--shadow-brand)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        display: ["var(--font-display)"],
        mono: ["var(--font-mono)"],
      },
      fontWeight: {
        bold: "var(--font-weight-bold)",
      },
      fontSize: {
        display: [
          "var(--text-display-size)",
          { lineHeight: "var(--text-display-line)" },
        ],
        h1: ["var(--text-h1-size)", { lineHeight: "var(--text-h1-line)" }],
        h2: ["var(--text-h2-size)", { lineHeight: "var(--text-h2-line)" }],
        body: ["var(--text-body-size)", { lineHeight: "var(--text-body-line)" }],
        small: [
          "var(--text-small-size)",
          { lineHeight: "var(--text-small-line)" },
        ],
      },
      minHeight: {
        touch: "var(--size-touch-min)",
      },
      minWidth: {
        touch: "var(--size-touch-min)",
      },
      zIndex: {
        dropdown: "var(--z-dropdown)",
        sticky: "var(--z-sticky)",
        modal: "var(--z-modal)",
        toast: "var(--z-toast)",
        "qr-overlay": "var(--z-qr-overlay)",
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        normal: "var(--duration-normal)",
        slow: "var(--duration-slow)",
      },
      transitionTimingFunction: {
        DEFAULT: "var(--ease-default)",
        out: "var(--ease-out)",
        spring: "var(--ease-spring)",
      },
    },
  },
  plugins: [],
};

export default config;
