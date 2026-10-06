import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    fsModuleCache: true,
    include: ["tests/component/**/*.test.{ts,tsx}", "tests/client/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
    restoreMocks: true,
    clearMocks: true,
    coverage: {
      provider: "v8",
      reportsDirectory: "coverage/combined",
      reporter: ["text", "json", "html"],
      reportOnFailure: true,
      include: [
        "app/**/*.{ts,tsx}",
        "components/**/*.{ts,tsx}",
        "features/**/*.{ts,tsx}",
        "lib/**/*.{ts,tsx}",
      ],
      exclude: [
        "**/*.d.ts",
        "**/*.test.{ts,tsx}",
        "**/*.spec.{ts,tsx}",
        "**/__tests__/**",
        "**/generated/**",
        "**/__generated__/**",
        "**/*.generated.{ts,tsx}",
        "**/node_modules/**",
        "**/.next/**",
        "**/coverage/**",
        "**/test-results/**",
        "app/page.tsx",
        "app/login/page.tsx",
        "app/session/renew/page.tsx",
        "app/restaurants/**/page.tsx",
        "app/restaurants/**/layout.tsx",
        "lib/api/server.ts",
      ],
    },
  },
});
