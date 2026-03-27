import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const rootEnvDir = path.resolve(__dirname, '..')

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, rootEnvDir, '')
  const apiUrl = env.VITE_API_URL || 'http://localhost:8001/api/v1'
  let proxyTarget = 'http://localhost:8001'

  try {
    proxyTarget = new URL(apiUrl).origin
  } catch {
    // Keep default proxy target if VITE_API_URL isn't an absolute URL.
  }

  return {
    envDir: rootEnvDir,
    plugins: [react()],
    server: {
      port: 80,
      host: true,
      allowedHosts: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true
        }
      }
    }
  }
})
