import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
// Dev-only allowance so impeccable live mode can load.
const __impeccableLiveDev = isDev ? " http://localhost:8400" : "";

/**
 * Content Security Policy (Milestone 7, ADR-020). Everything the app loads is same-origin: the
 * API is proxied on this origin, album covers come through the Next.js image optimizer, fonts
 * are self-hosted. Inline scripts are allowed because the App Router streams its payload in
 * inline scripts and nonces would require rendering every page per request (they are
 * incompatible with prerendering, which `cacheComponents` relies on). The policy still blocks
 * scripts and connections to any other origin, framing, plugins, <base> hijacking and form
 * posts elsewhere. React escapes all user text, so injected markup is never rendered as HTML.
 */
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}${__impeccableLiveDev}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws:" : ""}${__impeccableLiveDev}`,
  "media-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "worker-src 'self' blob:",
  "manifest-src 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  // Full URLs (which may carry a reset or verification token) never leave this origin.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  // Self-contained server bundle for the production Docker image (see Dockerfile).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  images: {
    // Album covers from the Cover Art Archive (MusicBrainz release groups). Images go through
    // the Next.js image optimizer: resized, cached, and fetched by our server rather than the
    // visitor's browser. The archive redirects to archive.org storage (followed automatically).
    remotePatterns: [new URL("https://coverartarchive.org/release-group/**")],
    minimumCacheTTL: 60 * 60 * 24 * 7,
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
