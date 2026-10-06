const fallback = "/dashboard/restaurants";

/** Only allow known workspace destinations; never navigate to a supplied origin. */
export function safeReturnPath(value: string | null | undefined): string {
  if (!value || /[\\\r\n]/.test(value) || !value.startsWith("/") || value.startsWith("//"))
    return fallback;
  const url = new URL(value, "https://restaurantos.invalid");
  if (url.origin !== "https://restaurantos.invalid") return fallback;
  if (
    url.pathname !== fallback &&
    !/^\/restaurants\/\d+\/(dashboard|orders|menu(?:\/\d+)?|inventory|employees)$/.test(
      url.pathname,
    )
  )
    return fallback;
  // Carry only supported pagination, never internal navigation/renewal flags.
  const offset = url.searchParams.get("offset");
  return url.pathname + (offset && /^\d+$/.test(offset) ? `?offset=${offset}` : "");
}

export function loginPath(next: string): string {
  return `/login?next=${encodeURIComponent(safeReturnPath(next))}`;
}
