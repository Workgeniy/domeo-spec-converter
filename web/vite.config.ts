import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В разработке фронт живёт на 5180 (5173 занят другими проектами Domeo), а запросы к /api
// уходят на ASP.NET Core API (порт 5080).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:5080',
    },
  },
})
