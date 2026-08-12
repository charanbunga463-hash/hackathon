/** @type {import('next').NextConfig} */

// Where /api/* is proxied to.
//
// IMPORTANT: `rewrites()` is evaluated at BUILD time and baked into
// `.next/routes-manifest.json`. Setting NEXT_PUBLIC_API_URL only in the
// container's runtime environment has no effect — the manifest still holds
// whatever was resolved during `next build`. That is why the Dockerfile takes
// it as an ARG and docker-compose passes it under `build.args`, not just
// `environment`. Getting this wrong is silent: the proxy falls back to
// 127.0.0.1:8000, which inside the frontend container is the frontend itself,
// and every API call returns 500.
const backend = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Proxy the API through Next so the browser sees one origin.
  // This keeps SSE and cookies working without CORS preflight surprises.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;
