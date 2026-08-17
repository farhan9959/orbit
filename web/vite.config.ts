import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// The dashboard and the API are same-origin in production: deploy/nginx.conf proxies /api/
// to the API container with proxy_buffering off, which is what keeps SSE flowing. The dev
// proxy reproduces that so the browser sees one origin here too. Adding CORS with
// credentials instead would widen the CSRF surface the threat model deliberately closes.
const api = { target: "http://127.0.0.1:8000", changeOrigin: false }

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": api, "/healthz": api } },
})
