import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/verify':  'http://127.0.0.1:8000',
      '/report':  'http://127.0.0.1:8000',
      '/health':  'http://127.0.0.1:8000',
      '/ingest':  'http://127.0.0.1:8000',
    },
  },
})
