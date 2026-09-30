import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend FastAPI berjalan di :8000 (python -m uvicorn api.app:app --port 8000).
// Proxy /api dan /maps agar frontend tak perlu tahu origin (bukan masalah CORS di dev).
export default defineConfig({
  plugins: [react()],
  server: {
    // 5173 sengaja dihindari — terpakai proyek lain di mesin ini
    port: 5199,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/maps': 'http://127.0.0.1:8000',
    },
  },
})
