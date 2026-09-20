import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const api = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node', include: ['src/**/*.test.{ts,tsx}'] },
  server: { proxy: { '/api': api, '/frame': api } },
})
