import fs from 'node:fs'
import path from 'node:path'
import { execSync, execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const frontendRoot = path.resolve(__dirname, '..')
const gitRoot = path.resolve(__dirname, '../../../..')

// Parse optional description: npm run release -- -m "description"
const msgIdx = process.argv.findIndex(a => a === '-m' || a === '--message')
const description = msgIdx !== -1 ? process.argv[msgIdx + 1] : null

// Increment patch version Z and reset build number N (X.Y.Z.N -> X.Y.(Z+1).0)
const versionFile = path.resolve(frontendRoot, 'src/version.ts')
const original = fs.readFileSync(versionFile, 'utf8')
const match = original.match(/APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)\.(\d+)'/)
if (!match) {
  console.error('[release] Cannot parse version from version.ts (expected X.Y.Z.N)')
  process.exit(1)
}
const [major, minor, patch] = [match[1], match[2], Number(match[3])]
const newVersion = `${major}.${minor}.${patch + 1}.0`
fs.writeFileSync(versionFile, `export const APP_VERSION = '${newVersion}'\n`)
console.log(`[release] ${match[1]}.${match[2]}.${match[3]}.${match[4]} -> ${newVersion}`)

// Build (restore version on failure)
try {
  execSync('npm run build', {
    cwd: frontendRoot,
    stdio: 'inherit',
    shell: true,
    env: { ...process.env, SKIP_BUILD_BUMP: '1' },
  })
} catch {
  fs.writeFileSync(versionFile, original)
  console.error('[release] Build failed — version restored')
  process.exit(1)
}

// Git commit + tag
const tag = `v${newVersion}`
const commitMsg = description ? `release: ${tag}\n\n${description}` : `release: ${tag}`
try {
  execSync(
    `git add code/dashboard/frontend/src/version.ts code/dashboard/static/`,
    { cwd: gitRoot, stdio: 'inherit', shell: true }
  )
  execFileSync('git', ['commit', '-m', commitMsg], { cwd: gitRoot, stdio: 'inherit' })
  execFileSync('git', ['tag', tag], { cwd: gitRoot, stdio: 'inherit' })
  console.log(`[release] committed and tagged ${tag}`)
} catch (err) {
  console.error('[release] Git step failed:', err.message)
  process.exit(1)
}
