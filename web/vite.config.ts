import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В разработке запросы к /api уходят на FastAPI (порт 8000), фронт — на 5173.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
