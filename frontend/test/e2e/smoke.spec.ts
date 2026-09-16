import { expect, test } from '@playwright/test'

const USERNAME = process.env.KAFKAPLAY_E2E_USER ?? 'admin'
const PASSWORD = process.env.KAFKAPLAY_E2E_PASSWORD ?? 'kafkaplay-dev-password'

test.describe('smoke', () => {
  test('health endpoint responds', async ({ request }) => {
    const response = await request.get('/healthz')
    expect(response.ok()).toBeTruthy()
    expect((await response.json()).status).toBe('ok')
  })

  test('readiness reports every check', async ({ request }) => {
    const body = await (await request.get('/readyz')).json()
    const names = body.checks.map((check: { name: string }) => check.name)
    expect(names).toEqual(expect.arrayContaining(['database', 'clusters', 'theme']))
  })

  test('cluster list requires authentication', async ({ request }) => {
    const response = await request.get('/api/v1/clusters')
    expect(response.status()).toBe(401)
  })

  test('sign in, see the shell, sign out', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
    await page.getByLabel(/username/i).fill(USERNAME)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /overview/i })).toBeVisible()

    await page.getByRole('button', { name: /sign out/i }).click()
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
  })

  test('rejects a wrong password without revealing whether the user exists', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel(/username/i).fill('definitely-not-a-user')
    await page.getByLabel(/password/i).fill('definitely-not-the-password')
    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(page.getByRole('alert')).toContainText(/invalid username or password/i)
  })

  test('dark mode toggle updates the document', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel(/username/i).fill(USERNAME)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page.getByRole('navigation', { name: /main navigation/i })).toBeVisible()
    const before = await page.evaluate(() => document.documentElement.dataset.theme)
    await page.getByRole('button', { name: /light mode|dark mode/i }).click()
    const after = await page.evaluate(() => document.documentElement.dataset.theme)
    expect(after).not.toBe(before)
  })

  test('navigating to a later-milestone page shows an honest empty state', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel(/username/i).fill(USERNAME)
    await page.getByLabel(/password/i).fill(PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()

    await page.getByRole('link', { name: /topics/i }).click()
    await expect(page.getByText(/not built yet/i)).toBeVisible()
  })
})
