import { defineConfig, devices } from '@playwright/test'

// Points at a running stack. In CI this is the dev compose stack; locally it
// can be `make dev` or the Vite dev server.
const BASE_URL = process.env.KAFKAPLAY_E2E_URL ?? 'http://127.0.0.1:8080'

export default defineConfig({
  testDir: './test/e2e',
  // Screenshots are generated on demand, not part of the CI smoke run.
  testIgnore: process.env.KAFKAPLAY_SCREENSHOTS ? [] : ['**/screenshots.spec.ts'],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
