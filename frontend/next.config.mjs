/** @type {import('next').NextConfig} */
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  // GitHub Pages: plain static files served from /order-supervisor
  ...(staticExport && {
    output: "export",
    basePath: process.env.BASE_PATH || "/order-supervisor",
    trailingSlash: true,
    images: { unoptimized: true },
  }),
};

export default nextConfig;
