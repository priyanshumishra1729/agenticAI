import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': backend,
      '/a2a': backend,
      '/.well-known': backend,
    },
  },
  preview: { host: '0.0.0.0', port: 4173 },
  build: { chunkSizeWarningLimit: 1200 },
})
