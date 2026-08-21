import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { build } from 'vite'


const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const root = path.resolve(__dirname, '..')

// Auto-increment build number N in X.Y.Z.N (skip when called from release.mjs)
//
// 同时写下**构建时间**。版本号只回答"代码改了没"，回答不了"这份页面是什么时候
// 构建的"——而"我改了但页面没变"最常见的原因恰恰是没重新构建、或浏览器拿的是
// 旧缓存。把构建时间显示在版本号旁边，这两件事一眼就分得开（用户 2026-08-21 提）。
if (!process.env.SKIP_BUILD_BUMP) {
  const versionFile = path.resolve(root, 'src/version.ts')
  const content = fs.readFileSync(versionFile, 'utf8')
  const m = content.match(/APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)\.(\d+)'/)
  if (m) {
    const newVer = `${m[1]}.${m[2]}.${m[3]}.${Number(m[4]) + 1}`
    const t = new Date()
    const pad = (n) => String(n).padStart(2, '0')
    const built = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())} `
      + `${pad(t.getHours())}:${pad(t.getMinutes())}`
    fs.writeFileSync(
      versionFile,
      `export const APP_VERSION = '${newVer}'\nexport const BUILT_AT = '${built}'\n`,
    )
    console.log(`[build] ${m[1]}.${m[2]}.${m[3]}.${m[4]} -> ${newVer}  (${built})`)
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
