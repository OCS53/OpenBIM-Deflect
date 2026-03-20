import { copyFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const wasmDir = join(root, 'public', 'wasm')
mkdirSync(wasmDir, { recursive: true })
copyFileSync(
  join(root, 'node_modules', 'web-ifc', 'web-ifc.wasm'),
  join(wasmDir, 'web-ifc.wasm'),
)
