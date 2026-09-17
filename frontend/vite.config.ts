import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'


// The dev server proxies to the backend so the browser sees one origin and
// session cookies behave exactly as they do in production.
const BACKEND = process.env.OFFSETSCOPE_BACKEND ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/brand': { target: BACKEND, changeOrigin: true },
      '/healthz': { target: BACKEND, changeOrigin: true },
      '/readyz': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Split the heavy, rarely-changing libraries so a UI change does not force
    // users to re-download ECharts. Vite 8 bundles with Rolldown, which takes
    // only the function form of manualChunks.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // echarts is dynamically imported; let the bundler emit it as its
          // own lazy chunk rather than forcing it into a static one.
          if (id.includes('node_modules/echarts')) return undefined
          if (/node_modules\/(react|react-dom|react-router)/.test(id)) return 'react'
          return undefined
        },
      },
    },
  },
})
