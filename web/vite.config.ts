import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В разработке запросы к /api уходят на ASP.NET Core API (порт 5080), фронт — на 5173.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:5080',
    },
  },
})
