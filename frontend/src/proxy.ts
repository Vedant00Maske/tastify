import { NextResponse, type NextRequest } from "next/server";

/**
 * 1. Forwards /api/v1/* to the FastAPI backend, so the browser only ever talks to this origin and
 *    the session cookie is first-party. API_PROXY_TARGET is read at runtime (default: local API).
 * 2. Optimistic auth redirects (Next.js "optimistic checks"): no session cookie on an app page
 *    -> /login; a session cookie on /login or /register -> /home. The API still verifies the
 *    session on every request; this only avoids rendering a page that would immediately 401.
 */
const SESSION_COOKIE = "soniqueo_session";
// Signed-in visitors are sent home from these.
const AUTH_PAGES = ["/login", "/register", "/forgot-password"];
// Reachable signed in or not: e-mailed links (the token is the proof) and the legal pages.
const PUBLIC_PAGES = new Set([
  "/",
  ...AUTH_PAGES,
  "/reset-password",
  "/verify-email",
  "/privacy",
  "/terms",
]);

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (pathname.startsWith("/api/v1/")) {
    const target = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
    return NextResponse.rewrite(new URL(`${pathname}${search}`, target));
  }

  const signedIn = request.cookies.has(SESSION_COOKIE);
  if (pathname === "/") {
    return NextResponse.redirect(
      new URL(signedIn ? "/home" : "/login", request.url),
    );
  }
  if (signedIn && AUTH_PAGES.includes(pathname)) {
    return NextResponse.redirect(new URL("/home", request.url));
  }
  if (!signedIn && !PUBLIC_PAGES.has(pathname)) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except Next.js internals and static files.
  matcher: [
    "/((?!_next/|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|webp|ico|txt)$).*)",
  ],
};
