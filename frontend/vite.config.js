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
  const apiUrl = env.VITE_API_URL || '/api/v1'
  const backendPort = env.API_PORT || '8001'
  const configuredProxyTarget = env.VITE_PROXY_TARGET || env.VITE_BACKEND_URL || `http://127.0.0.1:${backendPort}`
  let proxyTarget = configuredProxyTarget

  try {
    if (/^https?:\/\//i.test(apiUrl)) {
      proxyTarget = new URL(apiUrl).origin
    }
  } catch {
    // Keep configured proxy target if VITE_API_URL isn't an absolute URL.
  }

  // Windows/Node may resolve localhost to IPv6 first and Vite proxy can fail with EACCES.
  // FastAPI is still reachable on 127.0.0.1:8001 in local dev, so prefer IPv4 explicitly.
  proxyTarget = proxyTarget.replace('http://localhost:', 'http://127.0.0.1:')

  return {
    customLogger,
    envDir: rootEnvDir,
    plugins: [uriGuardPlugin, react()],
    server: {
      port: 5173,
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
