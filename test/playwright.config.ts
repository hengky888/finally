import { defineConfig, devices } from '@playwright/test';

/**
 * FinAlly is a single-user app: every spec shares one portfolio and one
 * database. Tests therefore run serially in file-name order, and the
 * `01-fresh-start` spec runs first against a pristine database.
 *
 * No retries on purpose. This app is live and asynchronous; a test that only
 * passes on the second attempt is hiding a defect, and the suite's job is to
 * surface those rather than to be green.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
