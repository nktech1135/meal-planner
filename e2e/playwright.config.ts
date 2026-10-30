import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 8799);

export default defineConfig({
  testDir: "tests",
  fullyParallel: false, // tests share one server and its first-account-is-admin rule
  workers: 1,
  retries: 0,
  // On CI, failures also become annotations on the run, readable without downloading the logs.
  reporter: process.env.CI ? [["list"], ["github"]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts/ },
    {
      name: "desktop",
      dependencies: ["setup"],
      use: { ...devices["Desktop Chrome"], storageState: "state/admin.json" },
    },
    {
      name: "phone",
      dependencies: ["setup"],
      testMatch: /layout\.spec\.ts/,
      use: { ...devices["Pixel 7"], colorScheme: "dark", storageState: "state/admin.json" },
    },
  ],
  webServer: {
    command: "./serve.sh",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { E2E_PORT: String(port) },
  },
});
