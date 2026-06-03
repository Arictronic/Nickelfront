import fs from 'fs'
import { createLogger, defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const rootEnvDir = path.resolve(__dirname, '..')
const logsDir = path.resolve(rootEnvDir, 'logs')
const frontendLogFile = path.resolve(logsDir, 'frontend_dev.log')

function writeFrontendLog(level, message) {
  try {
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true })
    }
    const ts = new Date().toISOString()
    fs.appendFileSync(frontendLogFile, `${ts} | ${level} | ${message}\n`, 'utf-8')
  } catch {
    // Keep dev-server running even if file logging fails.
  }
}

const uriGuardPlugin = {
  name: 'uri-guard',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      try {
        decodeURI(req.url || '/')
        next()
      } catch {
        res.statusCode = 400
        res.end('Bad Request: malformed URI')
      }
    })
  }
}

export default defineConfig(({ mode }) => {
  const defaultLogger = createLogger()
  const customLogger = {
    ...defaultLogger,
    info(msg, options) {
      writeFrontendLog('INFO', msg)
      defaultLogger.info(msg, options)
    },
    warn(msg, options) {
      writeFrontendLog('WARN', msg)
      defaultLogger.warn(msg, options)
    },
    error(msg, options) {
      writeFrontendLog('ERROR', msg)
      defaultLogger.error(msg, options)
    }
  }

  const env = loadEnv(mode, rootEnvDir, '')
  const apiUrl = String(env.VITE_API_URL || '/api/v1').trim()
  const backendPort = String(env.API_PORT || env.VITE_API_PORT || '8001').trim()
  const frontendPort = Number.parseInt(String(env.FRONTEND_PORT || env.VITE_PORT || '5173').trim(), 10) || 5173

  function normalizeProxyTarget(value) {
    const raw = String(value || '').trim()
    if (!raw) return null

    try {
      if (/^https?:\/\//i.test(raw)) {
        const url = new URL(raw)
        // Windows/Node may resolve localhost to IPv6 first and Vite proxy can fail with EACCES.
        if (url.hostname === 'localhost') {
          url.hostname = '127.0.0.1'
        }
        return url.origin
      }
    } catch {
      return null
    }

    // Relative values like /api/v1 are valid for frontend axios baseURL,
    // but they are NOT valid as Vite proxy target. Ignore them here.
    return null
  }

  const proxyTarget = (
    normalizeProxyTarget(env.VITE_PROXY_TARGET) ||
    normalizeProxyTarget(env.VITE_BACKEND_URL) ||
    normalizeProxyTarget(env.VITE_BACKEND_ROOT_URL) ||
    normalizeProxyTarget(apiUrl) ||
    `http://127.0.0.1:${backendPort || '8001'}`
  )

  writeFrontendLog('INFO', `Vite API base: ${apiUrl}; proxy target: ${proxyTarget}; port: ${frontendPort}`)

  return {
    customLogger,
    envDir: rootEnvDir,
    plugins: [uriGuardPlugin, react()],
    server: {
      port: frontendPort,
      host: true,
      allowedHosts: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
          xfwd: true,
          timeout: 300000,
          proxyTimeout: 300000,
          configure(proxy) {
            proxy.on('error', (err, req) => {
              const url = req?.url || ''
              writeFrontendLog('ERROR', `proxy ${url} -> ${proxyTarget}: ${err?.message || err}`)
            })
          }
        }
      }
    }
  }
})
