import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { build } from 'vite'


const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const root = path.resolve(__dirname, '..')

// Auto-increment build number N in X.Y.Z.N (skip when called from release.mjs)
if (!process.env.SKIP_BUILD_BUMP) {
  const versionFile = path.resolve(root, 'src/version.ts')
  const content = fs.readFileSync(versionFile, 'utf8')
  const m = content.match(/APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)\.(\d+)'/)
  if (m) {
    const newVer = `${m[1]}.${m[2]}.${m[3]}.${Number(m[4]) + 1}`
    fs.writeFileSync(versionFile, `export const APP_VERSION = '${newVer}'\n`)
    console.log(`[build] ${m[1]}.${m[2]}.${m[3]}.${m[4]} -> ${newVer}`)
  }
}

await build({
  configFile: false,
  root,
  base: '/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(root, 'src'),
    },
  },
  build: {
    outDir: path.resolve(root, '../static'),
    emptyOutDir: true,
  },
})
