import { NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  const configured = process.env.FRONTEND_BASE_URL;
  if (configured) {
    const target = new URL(configured);
    const current = request.nextUrl;
    // NextURL normalizes loopback names; Host preserves the browser origin.
    const browserOrigin = new URL(`${current.protocol}//${request.headers.get("host") ?? current.host}`);
    const loopback = ["localhost", "127.0.0.1", "[::1]"];
    if (loopback.includes(target.hostname) && loopback.includes(browserOrigin.hostname) && target.origin !== browserOrigin.origin && request.method === "GET") {
      return NextResponse.redirect(new URL(current.pathname + current.search, target));
    }
  }
  return NextResponse.next();
}
export const config = { matcher: ["/((?!api|_next|favicon.ico).*)"] };
