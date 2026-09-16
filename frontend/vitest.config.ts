import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.ts'

// Vitest 5 no longer reads a `test` block out of vite.config.ts, so the test
// configuration lives here and reuses the app config for aliases and plugins.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./test/setup.ts'],
      include: ['test/unit/**/*.test.{ts,tsx}'],
    },
  }),
)
