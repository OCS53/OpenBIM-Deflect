/**
 * IFC 뷰어(Three.js) 위에 fe_results 샘플 노드를 포인트 구름으로 오버랩.
 * 스칼라 색: von Mises(있으면) 아니면 |변위|.
 */
import { BufferGeometry, Color, Float32BufferAttribute, Points, PointsMaterial } from 'three'
import type { FeDisplacementBlock, FeResultsPayload } from '../api/types'

/** 수동 점 크기(Three `PointsMaterial.size`) 허용 범위 */
export const FE_POINT_SIZE_MIN = 1e-5
export const FE_POINT_SIZE_MAX = 64

export type FePointCloudOptions = {
  /** 참조 좌표 + scale×(ux,uy,uz). 0이면 INP 기준 위치만 */
  deformScale?: number
  /**
   * PointsMaterial `size` (Three.js, `sizeAttenuation` 시 거리에 따라 보이는 크기 변함).
   * **지정 시** 이 값만 사용(`FE_POINT_SIZE_MIN`~`FE_POINT_SIZE_MAX` 클램프). **미지정**이면 자동.
   */
  pointSize?: number
  /** false면 솔리드에 가리지 않고 항상 앞에 그림 */
  depthTest?: boolean
}

/** 오버랩 가능: 노드 id·변위·참조 좌표(x,y,z)가 있고, 최소 1개 유효 좌표 */
export function hasFePointCloudData(fe: FeResultsPayload | null): boolean {
  const d = fe?.displacement
  if (!d?.node_id?.length) return false
  const n = d.node_id.length
  if (d.ux?.length !== n || d.uy?.length !== n || d.uz?.length !== n) return false
  if (!d.x?.length || d.y?.length !== n || d.z?.length !== n) return false
  for (let i = 0; i < n; i++) {
    if (
      Number.isFinite(d.x[i]) &&
      Number.isFinite(d.y![i]) &&
      Number.isFinite(d.z![i])
    ) {
      return true
    }
  }
  return false
}

function collectValidIndices(d: FeDisplacementBlock): number[] {
  const n = d.node_id.length
  const ix: number[] = []
  if (!d.x?.length || d.x.length !== n) return ix
  for (let i = 0; i < n; i++) {
    if (
      Number.isFinite(d.x[i]) &&
      Number.isFinite(d.y![i]) &&
      Number.isFinite(d.z![i]) &&
      Number.isFinite(d.ux[i]) &&
      Number.isFinite(d.uy[i]) &&
      Number.isFinite(d.uz[i])
    ) {
      ix.push(i)
    }
  }
  return ix
}

/** IFC·메쉬 스케일(mm/m)에 덜 민감하도록 이전 VTK 뷰에 가깝게 작게 잡음 */
function autoPointSize(positions: Float32Array, count: number): number {
  if (count <= 0) return 3.5
  let minX = Infinity
  let minY = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let maxZ = -Infinity
  for (let i = 0; i < count; i++) {
    const b = i * 3
    const x = positions[b]
    const y = positions[b + 1]
    const z = positions[b + 2]
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    minZ = Math.min(minZ, z)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
    maxZ = Math.max(maxZ, z)
  }
  const ext = Math.max(maxX - minX, maxY - minY, maxZ - minZ, 1e-9)
  const raw = 1.25 + ext * 0.00012
  return Math.max(2, Math.min(9, raw))
}

export function createFeResultsOverlayPoints(
  fe: FeResultsPayload | null,
  options: FePointCloudOptions = {},
): Points | null {
  const d = fe?.displacement
  if (!d || !hasFePointCloudData(fe)) return null

  const indices = collectValidIndices(d)
  if (indices.length === 0) return null

  const deformScale = Number.isFinite(options.deformScale) ? options.deformScale! : 0
  const stress = fe?.stress
  const n = indices.length
  const scalars = new Float32Array(n)

  if (stress?.von_mises?.length && stress.node_id.length) {
    const map = new Map<number, number>()
    for (let i = 0; i < stress.node_id.length; i++) {
      map.set(stress.node_id[i], stress.von_mises[i])
    }
    for (let j = 0; j < n; j++) {
      const i = indices[j]!
      scalars[j] = map.get(d.node_id[i]) ?? 0
    }
  } else {
    for (let j = 0; j < n; j++) {
      const i = indices[j]!
      scalars[j] = Math.hypot(d.ux[i], d.uy[i], d.uz[i])
    }
  }

  let smin = Infinity
  let smax = -Infinity
  for (let j = 0; j < n; j++) {
    const v = scalars[j]!
    if (Number.isFinite(v)) {
      smin = Math.min(smin, v)
      smax = Math.max(smax, v)
    }
  }
  if (!Number.isFinite(smin) || !Number.isFinite(smax)) return null
  const span = smax - smin || 1

  const positions = new Float32Array(n * 3)
  const colors = new Float32Array(n * 3)
  const c = new Color()
  for (let j = 0; j < n; j++) {
    const i = indices[j]!
    positions[j * 3] = d.x![i] + deformScale * d.ux[i]
    positions[j * 3 + 1] = d.y![i] + deformScale * d.uy[i]
    positions[j * 3 + 2] = d.z![i] + deformScale * d.uz[i]
    const t = Math.max(0, Math.min(1, (scalars[j]! - smin) / span))
    c.setHSL(0.72 - t * 0.72, 0.92, 0.52)
    colors[j * 3] = c.r
    colors[j * 3 + 1] = c.g
    colors[j * 3 + 2] = c.b
  }

  const geom = new BufferGeometry()
  geom.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geom.setAttribute('color', new Float32BufferAttribute(colors, 3))

  const pointSize =
    options.pointSize != null && Number.isFinite(options.pointSize)
      ? Math.max(FE_POINT_SIZE_MIN, Math.min(FE_POINT_SIZE_MAX, options.pointSize))
      : autoPointSize(positions, n)

  const mat = new PointsMaterial({
    size: pointSize,
    vertexColors: true,
    transparent: true,
    opacity: 0.92,
    depthTest: options.depthTest !== false,
    sizeAttenuation: true,
  })

  const pts = new Points(geom, mat)
  pts.name = 'FeResultsOverlay'
  pts.renderOrder = 1
  return pts
}

export function disposeFeResultsOverlayPoints(pts: Points | null): void {
  if (!pts) return
  pts.geometry.dispose()
  const m = pts.material
  if (Array.isArray(m)) m.forEach((x) => x.dispose())
  else m.dispose()
}
