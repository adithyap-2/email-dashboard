import type { NextConfig } from "next";

// Static export: the FastAPI backend serves the built `out/` directory, so the
// whole app (dashboard + API + Microsoft login) lives on a single URL/port.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
