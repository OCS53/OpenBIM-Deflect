import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const target = resolve(root, 'node_modules/web-ifc-three/IFCLoader.js')
const needle =
  "import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils';"
const replacement =
  "import { mergeBufferGeometries as mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils';"

let s = readFileSync(target, 'utf8')
if (s.includes(replacement)) {
  process.exit(0)
}
if (!s.includes(needle)) {
  console.warn(
    '[patch-web-ifc-three] Expected import line missing; skip (upstream changed?)',
  )
  process.exit(0)
}
writeFileSync(target, s.replace(needle, replacement))
