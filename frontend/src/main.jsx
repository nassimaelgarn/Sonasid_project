import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// Session cookies for Microsoft SSO are issued from http://localhost:8000. Browsers treat
// 127.0.0.1 and localhost as different sites, so credentialed fetch from 127.0.0.1:5174 to
// localhost:8000 often omits those cookies and the app looks "not logged in".
if (typeof window !== 'undefined' && window.location.hostname === '127.0.0.1') {
  const { protocol, port, pathname, search, hash } = window.location
  const p = port ? `:${port}` : ''
  window.location.replace(`${protocol}//localhost${p}${pathname}${search}${hash}`)
}

// Prod VM : :5175 ou HTTP direct → HTTPS nginx (micro + cookies sécurisés).
if (typeof window !== 'undefined') {
  const { hostname, protocol, port, pathname, search, hash } = window.location
  const prodHost = 'sonasid-alexsys.westeurope.cloudapp.azure.com'
  const onProd = hostname === prodHost || hostname === '135.236.108.108'
  const needsHttps = protocol === 'http:' || port === '5175'
  if (onProd && needsHttps) {
    window.location.replace(`https://${prodHost}${pathname}${search}${hash}`)
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
