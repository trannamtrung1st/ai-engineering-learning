import type { NextConfig } from "next";

function apiRewriteTarget(): string {
  const base =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:3001";
  return base.replace(/\/$/, "");
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const apiOrigin = apiRewriteTarget();
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
