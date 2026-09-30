import { NextResponse, type NextRequest } from "next/server";

/** Preserve the requested deep link for server-rendered session renewal. */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("x-restaurantos-path", request.nextUrl.pathname + request.nextUrl.search);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = { matcher: ["/restaurants/:path*", "/dashboard/:path*"] };
