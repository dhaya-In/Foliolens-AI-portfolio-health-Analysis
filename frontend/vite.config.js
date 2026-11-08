import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the SPA and API share one origin through this proxy, so the
// SameSite auth cookies work without CORS. In production serve both behind one
// HTTPS reverse proxy (see README "Production deployment").
const API_TARGET = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: API_TARGET, changeOrigin: false } },
  },
  build: { sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
  },
})
