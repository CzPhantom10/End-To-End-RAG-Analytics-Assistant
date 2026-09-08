import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The built client is served by FastAPI from web/dist, so the target machine
// needs Python only - Node is required at build time.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
  },
})
