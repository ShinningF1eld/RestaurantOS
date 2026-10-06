import { defineConfig, devices } from "@playwright/test";

const webPort = Number(process.env.PLAYWRIGHT_WEB_PORT ?? "3000");

// Start the API separately against the same TEST_DATABASE_URL as fixture seeding.
// A production Next build exercises server rendering as deployed.
export default defineConfig({
  testDir: "./tests",
  testIgnore: ["**/component/**", "**/client/**"],
  outputDir: process.env.PLAYWRIGHT_ARTIFACTS
    ? `${process.env.PLAYWRIGHT_ARTIFACTS}/screenshots`
    : "test-results/browser/screenshots",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    [
      "junit",
      { outputFile: `${process.env.PLAYWRIGHT_ARTIFACTS ?? "test-results/browser"}/results.xml` },
    ],
  ],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "off", // Auth traces contain cookies/passwords; do not persist credentials.
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER
    ? undefined
    : {
        command: `npm run start -- --hostname localhost --port ${webPort}`,
        url: `http://localhost:${webPort}/login`,
        reuseExistingServer: false,
        timeout: 120_000,
      },
});
