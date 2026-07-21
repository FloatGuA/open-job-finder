import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted telemetry font (bundled into /static; no external CDN → no
// render-blocking first-paint stall when fonts.googleapis.com is slow/blocked).
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'
import '@fontsource/ibm-plex-mono/700.css'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
