import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxy = {
  '/auth': { target: 'http://127.0.0.1:8001', changeOrigin: true },
  '/chat': { target: 'http://127.0.0.1:8001', changeOrigin: true },
  '/healthz': { target: 'http://127.0.0.1:8001', changeOrigin: true },
  '/conversations': { target: 'http://127.0.0.1:8001', changeOrigin: true },
  '/db': { target: 'http://127.0.0.1:8001', changeOrigin: true },
}

const allowedHosts = [
  'localhost',
  '127.0.0.1',
  '135.236.108.108',
  'sonasid-alexsys.westeurope.cloudapp.azure.com',
  '.cloudapp.azure.com',
]

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5175,
    strictPort: true,
    allowedHosts,
    proxy,
  },
  preview: {
    host: true,
    port: 4173,
    allowedHosts,
    proxy,
  },
})
