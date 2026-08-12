import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Edge redirects between the signed-in and signed-out halves of the app.
 *
 * This only looks at whether a session cookie is *present*. It cannot validate
 * one — the cookie is opaque and the session record lives in Redis — and it is
 * not trying to: the backend rejects every unauthenticated API call, so a
 * forged cookie buys an empty shell and a wall of 401s.
 *
 * What it does buy is the absence of a flash: a signed-out visitor lands on
 * /login directly instead of rendering the dashboard, watching /auth/me fail,
 * and then being bounced.
 */

const SESSION_COOKIE = "apidoctor_session";

/** The homepage. Public, and the only page a signed-out visitor should land on. */
const HOME = "/";

/** Where a signed-in user belongs. */
const APP_HOME = "/dashboard";

/** Sign-in flow pages: reachable only while signed out. */
const AUTH_ROUTES = [
  "/login",
  "/register",
  "/verify-otp",
  "/forgot-password",
  "/reset-password",
];

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const isAuthRoute = AUTH_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
  const isHome = pathname === HOME;

  // A signed-in user has no use for the marketing page or the sign-in form.
  if (hasSession && (isHome || isAuthRoute)) {
    return NextResponse.redirect(new URL(APP_HOME, request.url));
  }

  // Everything else is application chrome and needs a session. The homepage is
  // deliberately excluded so a visitor with no account sees the product first
  // rather than a login form.
  if (!hasSession && !isHome && !isAuthRoute) {
    const target = new URL("/login", request.url);
    // Remember where they were headed so sign-in can return them there.
    target.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(target);
  }

  return NextResponse.next();
}

export const config = {
  // Everything except API proxying, Next internals and static assets.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|icon.svg|robots.txt).*)"],
};
