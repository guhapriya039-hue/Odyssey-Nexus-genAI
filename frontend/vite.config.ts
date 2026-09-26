import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend serves the built frontend itself, so in production the
// dashboard is same-origin. In development we proxy /api to keep that shape.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.ODYSSEY_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
