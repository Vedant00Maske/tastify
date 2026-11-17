import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the production Docker image (see Dockerfile).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  images: {
    // Album covers from the Cover Art Archive (MusicBrainz release groups). Images go through
    // the Next.js image optimizer: resized, cached, and fetched by our server rather than the
    // visitor's browser. The archive redirects to archive.org storage (followed automatically).
    remotePatterns: [new URL("https://coverartarchive.org/release-group/**")],
    minimumCacheTTL: 60 * 60 * 24 * 7,
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
