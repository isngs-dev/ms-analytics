import { NextResponse, type NextRequest } from "next/server";

// Cheap gate: no session cookie -> login. The API still validates the token on every request.
export function middleware(req: NextRequest) {
  if (!req.cookies.get("ms_session")) {
    const url = req.nextUrl.clone();
    const next = req.nextUrl.pathname + req.nextUrl.search;
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(next)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!api|login|_next|favicon.ico).*)"] };
