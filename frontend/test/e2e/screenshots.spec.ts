import { expect, test, type Page } from '@playwright/test'

/**
 * Generates the screenshots in docs/screenshots.
 *
 * Kept as a spec rather than a manual capture so the images cannot drift from
 * the real UI: regenerate by running this against the dev stack.
 */

const USERNAME = process.env.OFFSETSCOPE_E2E_USER ?? 'admin'
const PASSWORD = process.env.OFFSETSCOPE_E2E_PASSWORD ?? 'offsetscope-dev-password'
const OUT = '../docs/screenshots'

const PAGES: [string, string][] = [
  ['/', 'overview'],
  ['/topics', 'topics'],
  ['/consumer-groups', 'consumer-groups'],
  ['/messages', 'messages'],
  ['/replication', 'replication'],
  ['/metrics', 'metrics'],
  ['/dashboards', 'dashboards'],
  ['/flow-map', 'flow-map'],
  ['/alerts', 'alerts'],
  ['/audit', 'audit'],
  ['/settings', 'settings'],
]

async function login(page: Page) {
  await page.goto('/')
  const username = page.getByLabel(/username/i)
  if (await username.isVisible().catch(() => false)) {
    await username.fill(USERNAME)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
  }
}

test.describe('screenshots', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  for (const mode of ['light', 'dark'] as const) {
    test(`capture ${mode} theme`, async ({ page }) => {
      await login(page)

      await page.evaluate((target) => {
        document.documentElement.dataset.theme = target
        try {
          localStorage.setItem('offsetscope.color-mode', target)
        } catch {
          // Storage may be blocked; the attribute alone is enough here.
        }
      }, mode)

      for (const [path, name] of PAGES) {
        await page.goto(path)
        // Let skeletons resolve so the capture shows real content.
        await page.waitForTimeout(1200)
        await page.screenshot({
          path: `${OUT}/${name}-${mode}.png`,
          fullPage: false,
        })
      }

      // The command palette is a modal, so it needs its own capture.
      await page.goto('/')
      await page.keyboard.press('Control+k')
      await page.waitForTimeout(400)
      await page.screenshot({ path: `${OUT}/command-palette-${mode}.png` })
    })
  }
})
