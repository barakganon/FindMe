import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for FindMe kill-gate / launch-validation E2E suite.
 *
 * Targets the dev stack (vite :5173 -> proxies /api to uvicorn :8000).
 * baseURL is env-overridable so this can point at a staging/Render URL later
 * without touching this file.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // conversation tests share localStorage state deliberately
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
