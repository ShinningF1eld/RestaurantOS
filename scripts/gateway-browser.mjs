// Real Chromium through the disposable HTTPS gateway. No traces, HAR or credentials in reports.
import fs from "node:fs";
import path from "node:path";
import tls from "node:tls";
import { createHash, randomUUID, X509Certificate } from "node:crypto";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";

const root = process.cwd();
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium, request, expect } = require("@playwright/test");
const run = process.env.GATEWAY_BROWSER_STATE;
if (!/^browser-[0-9a-f]{12}$/.test(run ?? ""))
  throw new Error("Owned browser state required");
const stateDir = path.join(root, ".local-gateway", run);
const state = JSON.parse(
  fs.readFileSync(path.join(stateDir, "state.json"), "utf8"),
);
if (state.browser_run !== true) throw new Error("Disposable marker required");
const origin = "https://localhost:" + state.port;
const ca = fs.readFileSync(path.join(stateDir, "root.crt"));
const headers = { Origin: origin, "X-CSRF-Protection": "1" };
const report = {
  cases: [],
  observations: {},
  limitations: [
    "native ARM",
    "host reboot",
    "two public egress addresses",
    "native browser trust-store validation",
  ],
};
const secrets = new Set();
const captures = [];
let captureErrors = 0;
const contexts = [];
let browser;
let activeCase = "setup";
let operation = "setup";
class CheckError extends Error {}
function ensure(condition, label) {
  if (!condition) throw new CheckError(label);
}
function fixture(action, data = {}) {
  operation = "trusted fixture " + action;
  const result = spawnSync(
    process.env.GATEWAY_BROWSER_PYTHON,
    [
      path.join(root, "scripts/run-gateway-browser-tests.py"),
      "--fixture",
      action,
      "--state",
      run,
    ],
    {
      input: JSON.stringify(data),
      encoding: "utf8",
      timeout: 150000,
      windowsHide: true,
    },
  );
  ensure(result.status === 0, "trusted fixture failed");
  return JSON.parse(result.stdout);
}
async function phase(name, body) {
  activeCase = name;
  await body();
  report.cases.push({ name, status: "passed" });
  fs.writeFileSync(
    process.env.GATEWAY_BROWSER_REPORT,
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log("PASS: " + name);
}
async function verifiedKey() {
  operation = "strict TLS hostname and chain validation";
  return new Promise((resolve, reject) => {
    const socket = tls.connect(
      {
        host: "localhost",
        port: state.port,
        servername: "localhost",
        ca,
        rejectUnauthorized: true,
      },
      () => {
        try {
          ensure(socket.authorized, "TLS chain not authorized");
          const cert = new X509Certificate(socket.getPeerCertificate().raw);
          const key = createHash("sha256")
            .update(cert.publicKey.export({ type: "spki", format: "der" }))
            .digest("base64");
          socket.end();
          resolve(key);
        } catch (error) {
          socket.destroy();
          reject(error);
        }
      },
    );
    socket.on("error", () => reject(new CheckError("strict TLS failed")));
  });
}
async function makeContext() {
  const context = await browser.newContext({
    baseURL: origin,
    ignoreHTTPSErrors: false,
  });
  contexts.push(context);
  context.on("response", (response) => {
    if (response.url().startsWith(origin + "/backend/auth/"))
      captures.push(
        captureCookies(response).catch(() => {
          captureErrors++;
        }),
      );
  });
  return context;
}
async function captureCookies(response) {
  for (const header of await response.headersArray()) {
    const match =
      header.name.toLowerCase() === "set-cookie" &&
      /^(?:ros_access|ros_refresh)=([^;]+)/.exec(header.value);
    if (match) {
      const value = match[1].replaceAll('"', "");
      if (value) secrets.add(value);
    }
  }
}
async function account(label) {
  const value = {
    email: "gateway-" + label + "-" + randomUUID() + "@example.test",
    password: randomUUID() + randomUUID(),
  };
  secrets.add(value.password);
  fixture("create", value);
  return value;
}
async function call(client, method, url, data, expected = 200) {
  operation = "authenticated API operation";
  const response = await client.fetch("/backend" + url, {
    method,
    headers,
    data,
  });
  await captureCookies(response);
  ensure(response.status() === expected, "unexpected authenticated API status");
  return response;
}
async function setupOwner(user, label) {
  const api = await request.newContext({
    baseURL: origin,
    ignoreHTTPSErrors: false,
  });
  await call(api, "POST", "/auth/login", user);
  await call(
    api,
    "POST",
    "/api/organizations",
    { name: "Gateway " + label, slug: "gateway-" + randomUUID() },
    201,
  );
  const restaurant = await (
    await call(api, "POST", "/api/restaurants", { name: label }, 201)
  ).json();
  const marker = label + "-" + randomUUID();
  const menu = await (
    await call(api, "POST", "/restaurants/" + restaurant.id + "/menus", {
      name: marker,
    })
  ).json();
  return { api, restaurant: restaurant.id, menu: menu.menu_id, marker };
}
async function signIn(page, user, next = "/dashboard/restaurants") {
  operation = "browser login page";
  await page.goto(origin + "/login?next=" + encodeURIComponent(next));
  await page.getByLabel("Email", { exact: true }).fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill(user.password);
  operation = "browser login submit";
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(origin + next);
  await expect(page.getByText(user.email, { exact: true })).toBeVisible();
}
async function remember(context) {
  const cookies = await context.cookies();
  for (const cookie of cookies)
    if (cookie.name.startsWith("ros_")) secrets.add(cookie.value);
  return cookies;
}
async function expire(context) {
  const cookies = await remember(context);
  const access = cookies.find((cookie) => cookie.name === "ros_access");
  ensure(access, "access cookie missing before expiry");
  const expired = fixture("expire", { token: access.value }).token;
  secrets.add(expired);
  await context.addCookies([{ ...access, value: expired }]);
}
async function noSecretStorage(page, context) {
  await remember(context);
  const body = await page.content();
  const storage = await page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
      cookie: document.cookie,
    }),
  );
  for (const value of secrets)
    ensure(
      !body.includes(value) && !storage.includes(value),
      "credential entered DOM or JavaScript storage",
    );
}
async function absent(page, marker) {
  await expect
    .poll(async () => !(await page.content()).includes(marker), {
      timeout: 15000,
    })
    .toBe(true);
}
function refreshCounter(context) {
  const value = { count: 0 };
  const listener = (req) => {
    if (req.url() === origin + "/backend/auth/refresh") value.count++;
  };
  context.on("request", listener);
  return { value, stop: () => context.off("request", listener) };
}
async function main() {
  const key = await verifiedKey();
  await phase("certificate negative control", async () => {
    const untrusted = await chromium.launch({ headless: true });
    try {
      const context = await untrusted.newContext({ ignoreHTTPSErrors: false });
      const page = await context.newPage();
      let rejected = false;
      try {
        await page.goto(origin + "/login");
      } catch {
        rejected = true;
      }
      ensure(rejected, "untrusted local CA was accepted without scoped key");
    } finally {
      await untrusted.close();
    }
  });
  const args = ["--ignore-certificate-errors-spki-list=" + key];
  browser = await chromium.launch({
    headless: true,
    args,
    ignoreDefaultArgs: ["--disable-back-forward-cache"],
  });
  const a = await account("owner-a");
  const b = await account("owner-b");
  const manager = await account("manager");
  const ownerA = await setupOwner(a, "A-private-menu");
  const ownerB = await setupOwner(b, "B-private-menu");
  const membership = await (
    await call(
      ownerA.api,
      "POST",
      "/api/memberships",
      {
        email: manager.email,
        role: "MANAGER",
        restaurant_ids: [ownerA.restaurant],
      },
      201,
    )
  ).json();
  const urlA = "/restaurants/" + ownerA.restaurant + "/menu";
  const urlB = "/restaurants/" + ownerB.restaurant + "/menu";
  const context = await makeContext();
  const page = await context.newPage();
  await phase("secure cookies and browser request boundary", async () => {
    await signIn(page, a, urlA);
    ensure(
      await page.evaluate(() => window.isSecureContext),
      "browser context is not secure",
    );
    const cookies = await remember(context);
    for (const name of ["ros_access", "ros_refresh"]) {
      const cookie = cookies.find((c) => c.name === name);
      ensure(
        cookie && cookie.secure && cookie.httpOnly && cookie.sameSite === "Lax",
        "cookie security attributes",
      );
      ensure(cookie.domain === "localhost", "cookie must be host only");
      ensure(
        cookie.path === (name === "ros_access" ? "/" : "/backend/auth"),
        "cookie scope",
      );
    }
    const rejected = await page.evaluate(
      async () =>
        (await fetch("/backend/auth/logout", { method: "POST" })).status,
    );
    ensure(rejected === 403, "unsafe request without CSRF accepted");
    await noSecretStorage(page, context);
  });
  if (process.env.GATEWAY_BROWSER_INJECT_FAILURE === "1") {
    activeCase = "intentional failure";
    throw new CheckError("intentional failure");
  }
  await phase("expired JWT SSR renews exactly once", async () => {
    const old = (await remember(context)).find(
      (c) => c.name === "ros_refresh",
    ).value;
    await expire(context);
    const ssr = await context.request.get(urlA, { maxRedirects: 0 });
    ensure(
      !(await ssr.headersArray()).some(
        (h) => h.name.toLowerCase() === "set-cookie",
      ),
      "SSR rotated cookies",
    );
    const counter = refreshCounter(context);
    await page.goto(origin + urlA);
    await expect(page.getByText(ownerA.marker, { exact: true })).toBeVisible();
    ensure(counter.value.count === 1, "SSR renewal count");
    ensure(
      (await remember(context)).find((c) => c.name === "ros_refresh").value !==
        old,
      "refresh did not rotate",
    );
    counter.stop();
    await noSecretStorage(page, context);
  });
  await phase("concurrent tabs serialize refresh", async () => {
    const tabs = await makeContext();
    const first = await tabs.newPage();
    await signIn(first, a, urlA);
    const second = await tabs.newPage();
    await second.goto(origin + urlA);
    await expect(second.getByText(a.email, { exact: true })).toBeVisible();
    await expire(tabs);
    const counter = refreshCounter(tabs);
    operation = "reload concurrent expired tabs";
    await Promise.all([first.reload(), second.reload()]);
    await expect(first.getByText(a.email, { exact: true })).toBeVisible();
    await expect(second.getByText(a.email, { exact: true })).toBeVisible();
    ensure(counter.value.count === 1, "concurrent rotation count");
    counter.stop();
    await remember(tabs);
    await tabs.close();
  });
  await phase("tenant API HTML RSC and navigation isolation", async () => {
    const other = await makeContext();
    const otherPage = await other.newPage();
    await signIn(otherPage, b, urlB);
    const inspect = async (ctx, own, foreign, ownUrl, foreignUrl) => {
      for (let warm = 0; warm < 2; warm++) {
        const ownApi = await ctx.request.get(
          "/backend/restaurants/" + own.restaurant + "/menus",
        );
        ensure(
          ownApi.status() === 200 && (await ownApi.text()).includes(own.marker),
          "warm own catalog",
        );
      }
      const foreignApi = await ctx.request.get(
        "/backend/restaurants/" + foreign.restaurant + "/menus",
      );
      ensure(
        foreignApi.status() === 404 &&
          !(await foreignApi.text()).includes(foreign.marker),
        "foreign API leaked",
      );
      const ownRsc = await ctx.request.get(ownUrl, { headers: { RSC: "1" } });
      ensure(
        (ownRsc.headers()["content-type"] ?? "").includes("text/x-component"),
        "RSC response not exercised",
      );
      ensure(
        (await ownRsc.text()).includes(own.marker),
        "own RSC marker missing",
      );
      for (const requestHeaders of [{}, { RSC: "1" }]) {
        const response = await ctx.request.get(foreignUrl, {
          headers: requestHeaders,
        });
        ensure(
          !(await response.text()).includes(foreign.marker),
          "foreign HTML or RSC leaked",
        );
      }
    };
    await inspect(context, ownerA, ownerB, urlA, urlB);
    await inspect(other, ownerB, ownerA, urlB, urlA);
    await otherPage.getByRole("link", { name: "Orders", exact: true }).click();
    await otherPage.getByRole("link", { name: "Menu", exact: true }).click();
    await expect(
      otherPage.getByText(ownerB.marker, { exact: true }),
    ).toBeVisible();
    await absent(otherPage, ownerA.marker);
    await otherPage.goto(origin + urlA);
    await absent(otherPage, ownerA.marker);
    await other.close();
  });
  await phase("warm assignment and membership revocation", async () => {
    const ctx = await makeContext();
    const p = await ctx.newPage();
    await signIn(p, manager, urlA);
    await expect(p.getByText(ownerA.marker, { exact: true })).toBeVisible();
    await ctx.request.get(
      "/backend/restaurants/" + ownerA.restaurant + "/menus",
    );
    await call(ownerA.api, "PUT", "/api/memberships/" + membership.id, {
      restaurant_ids: [],
    });
    ensure(
      (
        await ctx.request.get(
          "/backend/restaurants/" + ownerA.restaurant + "/menus",
        )
      ).status() === 404,
      "revoked assignment served warm data",
    );
    await p.reload();
    await absent(p, ownerA.marker);
    await call(
      ownerA.api,
      "DELETE",
      "/api/memberships/" + membership.id,
      undefined,
      204,
    );
    ensure(
      (await ctx.request.get("/backend/api/access")).status() === 403,
      "revoked membership retained access",
    );
    await ctx.close();
  });
  await phase("committed refresh response loss does not replay", async () => {
    const ctx = await makeContext();
    const p = await ctx.newPage();
    await signIn(p, a, urlA);
    await expire(ctx);
    const before = await remember(ctx);
    let count = 0;
    await ctx.route("**/backend/auth/refresh", async (route) => {
      count++;
      const response = await route.fetch();
      await captureCookies(response);
      ensure(
        response.status() === 200,
        "refresh did not commit before response loss",
      );
      // Route.fetch may update the APIRequestContext jar. Restore the browser's
      // original cookies to model a response lost before any Set-Cookie delivery.
      await ctx.addCookies(before);
      await route.abort("failed");
    });
    await p.goto(origin + urlA);
    await expect(p.getByRole("alert")).toBeVisible();
    await p.getByRole("link", { name: "Go to sign in", exact: true }).click();
    await expect(p).toHaveURL(/\/login(?:\?|$)/);
    ensure(count === 1, "ambiguous refresh automatically replayed");
    await ctx.close();
  });
  await phase(
    "logout account switch history and restored profile",
    async () => {
      const profile = path.join(stateDir, "identity-profile");
      let persistent = await chromium.launchPersistentContext(profile, {
        headless: true,
        args,
        ignoreHTTPSErrors: false,
        ignoreDefaultArgs: ["--disable-back-forward-cache"],
      });
      let persisted = 0;
      try {
        await persistent.exposeBinding("gatewayPageshow", (_, value) => {
          if (value) persisted++;
        });
        await persistent.addInitScript(() =>
          window.addEventListener("pageshow", (event) =>
            window.gatewayPageshow(event.persisted),
          ),
        );
        const p = persistent.pages()[0] ?? (await persistent.newPage());
        await signIn(p, a, urlA);
        // Full-document navigation exercises BFCache; client navigation alone
        // only exercises the Next router cache.
        await p.goto(origin + "/");
        await p.goBack();
        await expect(p.getByText(ownerA.marker, { exact: true })).toBeVisible();
        await p.getByRole("link", { name: "Orders", exact: true }).click();
        await p.getByRole("link", { name: "Menu", exact: true }).click();
        await p.getByRole("button", { name: "Sign out", exact: true }).click();
        await expect(p).toHaveURL(/\/login(?:\?|$)/);
        await signIn(p, b, urlB);
        for (let back = 0; back < 3; back++) {
          await p.goBack();
          await absent(p, ownerA.marker);
        }
        await p.goForward();
        await absent(p, ownerA.marker);
        await p.goto(origin + urlB);
        await expect(p.getByText(ownerB.marker, { exact: true })).toBeVisible();
        await persistent.close();
        persistent = await chromium.launchPersistentContext(profile, {
          headless: true,
          args: [...args, "--restore-last-session"],
          ignoreHTTPSErrors: false,
        });
        const restored = persistent.pages()[0] ?? (await persistent.newPage());
        await restored.goto(origin + urlA);
        await absent(restored, ownerA.marker);
        await restored.goto(origin + urlB);
        await expect(
          restored.getByText(b.email, { exact: true }),
        ).toBeVisible();
        await expect(
          restored.getByText(ownerB.marker, { exact: true }),
        ).toBeVisible();
        report.observations.bfcachePersistedEvents = persisted;
        if (!persisted)
          report.limitations.push(
            "BFCache restoration attempted but not observed",
          );
      } finally {
        await persistent.close();
      }
    },
  );
  await phase("pre restart credential log privacy", async () => {
    await Promise.all(captures);
    ensure(!captureErrors, "auth response observation failed");
    ensure(
      fixture("privacy", { secrets: [...secrets] }).clean,
      "credential appeared before restart",
    );
  });
  await phase("controlled identity before restart", async () => {
    const login = await account("ip-before-login");
    const refresh = await account("ip-before-refresh");
    report.observations.identityBeforeRestart = fixture("identity", {
      origin,
      login,
      refresh,
    });
  });
  await phase(
    "container restart preserves session and worker effect",
    async () => {
      const newMenu = await (
        await call(
          ownerA.api,
          "POST",
          "/restaurants/" + ownerA.restaurant + "/menus",
          { name: "Restart worker probe" },
        )
      ).json();
      await expect
        .poll(
          () =>
            fixture("receipt", {
              restaurant: ownerA.restaurant,
              menu: newMenu.menu_id,
            }).count,
          { timeout: 45000 },
        )
        .toBe(1);
      await remember(context);
      fixture("restart");
      ensure(
        (await verifiedKey()) === key,
        "certificate identity changed across restart",
      );
      await page.goto(origin + urlA);
      await expect(page.getByText(a.email, { exact: true })).toBeVisible();
      await expect(
        page.getByText(ownerA.marker, { exact: true }),
      ).toBeVisible();
      ensure(
        fixture("receipt", {
          restaurant: ownerA.restaurant,
          menu: newMenu.menu_id,
        }).count === 1,
        "durable receipt changed across restart",
      );
    },
  );
  await phase(
    "distinct local peers preserve client identity and quotas",
    async () => {
      const login = await account("ip-login");
      const refresh = await account("ip-refresh");
      report.observations.identity = fixture("identity", {
        origin,
        login,
        refresh,
      });
    },
  );
  await phase("credentials absent from retained application logs", async () => {
    await Promise.all(captures);
    ensure(!captureErrors, "auth response observation failed");
    await noSecretStorage(page, context);
    ensure(
      fixture("privacy", { secrets: [...secrets] }).clean,
      "credential appeared in application logs",
    );
  });
}
try {
  await main();
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.cases.push({
    name: activeCase,
    status: "failed",
    reason: error instanceof CheckError ? error.message : operation,
  });
  console.log("FAIL: " + activeCase.replace(/[^A-Za-z0-9 _-]/g, ""));
  process.exitCode = 1;
} finally {
  for (const context of contexts) await context.close().catch(() => {});
  if (browser) await browser.close().catch(() => {});
  fs.writeFileSync(
    process.env.GATEWAY_BROWSER_REPORT,
    JSON.stringify(report, null, 2) + "\n",
  );
}
