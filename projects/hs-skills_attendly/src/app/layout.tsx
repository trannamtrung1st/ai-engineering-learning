import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Attendly",
  description: "Smart campus attendance",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          padding: "2rem",
          background: "#f4f7fb",
          color: "#172033",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: 720,
            margin: "0 auto",
            padding: "2rem",
            background: "white",
            borderRadius: 16,
          }}
        >
          {children}
        </div>
      </body>
    </html>
  );
}
