import { describe, expect, it, vi } from "vitest";

function response(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

async function loadClient() {
  vi.resetModules();
  return import("@/lib/api/client");
}

function installLocks() {
  const request = vi.fn(async (_name: string, callback: () => Promise<unknown> | unknown) =>
    callback(),
  );
  vi.stubGlobal("navigator", { locks: { request } });
  return request;
}

function installWindow() {
  const location = {
    pathname: "/restaurants/17/orders",
    search: "?offset=20",
    replace: vi.fn(),
  };
  vi.stubGlobal("window", { location });
  return location;
}

describe("browser API client", () => {
  it("includes cookies and CSRF protection on writes, and rejects unsafe paths", async () => {
    const fetchMock = vi.fn(async () => response(200, { saved: true }));
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await loadClient();

    await apiFetch("/api/restaurants", {
      method: "POST",
      body: JSON.stringify({ name: "Demo" }),
    });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("error");
    expect(headers.get("X-CSRF-Protection")).toBe("1");
    expect(headers.get("Content-Type")).toBe("application/json");
    await expect(apiFetch("//evil.example/path")).rejects.toThrow("Invalid API path");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries one explicit 401 after renewal and coalesces concurrent renewal requests", async () => {
    const lockRequest = installLocks();
    const counts = new Map<string, number>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      if (path === "/auth/me") return response(401, { detail: "Expired" });
      if (path === "/auth/refresh") return response(200, { ok: true });
      const count = (counts.get(path) ?? 0) + 1;
      counts.set(path, count);
      return response(count === 1 ? 401 : 200, { ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await loadClient();

    const results = await Promise.all([apiFetch("/api/one"), apiFetch("/api/two")]);

    expect(results).toHaveLength(2);
    expect(counts).toEqual(
      new Map([
        ["/api/one", 2],
        ["/api/two", 2],
      ]),
    );
    expect(
      fetchMock.mock.calls.filter(([input]) => new URL(String(input)).pathname === "/auth/refresh"),
    ).toHaveLength(1);
    expect(lockRequest).toHaveBeenCalledTimes(1);
    expect(lockRequest.mock.calls[0]?.[0]).toBe("restaurantos-session-mutation");
  });

  it("does not retry an ambiguous business failure or a renewal service failure", async () => {
    installLocks();
    const paths: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      paths.push(path);
      return path === "/api/write"
        ? response(503, { detail: "Unavailable" })
        : response(200, { ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await loadClient();

    await expect(apiFetch("/api/write", { method: "POST", body: "{}" })).rejects.toMatchObject({
      status: 503,
    });
    expect(paths).toEqual(["/api/write"]);

    paths.length = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      paths.push(path);
      if (path === "/api/read") return response(401, { detail: "Expired" });
      if (path === "/auth/me") return response(503, { detail: "Unavailable" });
      return response(200, { ok: true });
    });
    await expect(apiFetch("/api/read")).rejects.toMatchObject({ status: 503 });
    expect(paths).toEqual(["/api/read", "/auth/me"]);
  });

  it("locks out repeated refresh attempts after a rejected renewal", async () => {
    installLocks();
    const location = installWindow();
    const paths: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      paths.push(path);
      if (path === "/auth/me" || path === "/api/read") return response(401, { detail: "Expired" });
      return response(401, { detail: "Refresh token was rejected" });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await loadClient();

    await expect(apiFetch("/api/read")).rejects.toMatchObject({ status: 401 });
    await expect(apiFetch("/api/read")).rejects.toMatchObject({ status: 401 });

    expect(paths.filter((path) => path === "/auth/refresh")).toHaveLength(1);
    expect(paths.filter((path) => path === "/api/read")).toHaveLength(2);
    expect(location.replace).toHaveBeenCalledWith(
      "/login?next=%2Frestaurants%2F17%2Forders%3Foffset%3D20",
    );
  });
});
