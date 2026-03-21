import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AmbientLight,
  Box3,
  Color,
  DirectionalLight,
  GridHelper,
  Group,
  type Material,
  type Mesh,
  Object3D,
  PerspectiveCamera,
  type Points,
  Scene,
  Vector3,
  WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { IFCLoader } from 'web-ifc-three'
import {
  createFeResultsOverlayPoints,
  disposeFeResultsOverlayPoints,
  FE_POINT_SIZE_MAX,
  FE_POINT_SIZE_MIN,
  hasFePointCloudData,
} from '../analysis/feResultsOverlayThree'
import { inferIfcLengthScaleToMeters } from '../analysis/ifcLengthScale'
import type { FeResultsPayload } from '../api/types'
import './IfcViewer.css'

type IfcViewerMesh = Mesh & { close: (scene?: Object3D) => void }

function fitCameraToObject(
  camera: PerspectiveCamera,
  controls: OrbitControls,
  object: Group,
  margin = 1.25,
) {
  const box = new Box3().setFromObject(object)
  const size = box.getSize(new Vector3())
  const center = box.getCenter(new Vector3())
  const maxDim = Math.max(size.x, size.y, size.z) || 1
  const dist = maxDim / (2 * Math.tan((camera.fov * Math.PI) / 360)) * margin
  const dir = new Vector3(1, 1, 1).normalize()
  camera.position.copy(center.clone().add(dir.multiplyScalar(dist)))
  camera.near = Math.max(dist / 100, 0.01)
  camera.far = dist * 100
  camera.updateProjectionMatrix()
  controls.target.copy(center)
  controls.update()
}

function pickGridCellSize(maxDim: number): number {
  if (maxDim < 10) return 0.5
  if (maxDim < 25) return 1
  if (maxDim < 60) return 2
  return 5
}

function updateFloorGrid(
  scene: Scene,
  root: Group,
  gridRef: { current: GridHelper | null },
): { sizeX: number; sizeZ: number; cellSize: number } | null {
  const box = new Box3().setFromObject(root)
  const size = box.getSize(new Vector3())
  const center = box.getCenter(new Vector3())
  const floorY = box.min.y
  const maxDim = Math.max(size.x, size.z) || 1
  if (maxDim < 0.01) return null

  const cellSize = pickGridCellSize(maxDim)
  const rawSize = Math.max(size.x, size.z) * 1.3
  const divisions = Math.max(2, Math.ceil(rawSize / cellSize))
  const gridSize = divisions * cellSize

  if (gridRef.current) {
    scene.remove(gridRef.current)
    gridRef.current.dispose()
    gridRef.current = null
  }
  const grid = new GridHelper(gridSize, divisions, 0x444a54, 0x2a3038)
  grid.position.set(center.x, floorY, center.z)
  scene.add(grid)
  gridRef.current = grid
  return { sizeX: gridSize, sizeZ: gridSize, cellSize }
}

function setModelWireframe(model: Object3D, wireframe: boolean) {
  const setWire = (m: Material | Material[]): void => {
    if (Array.isArray(m)) m.forEach((mm) => setWire(mm))
    else if (m && 'wireframe' in m) (m as Material & { wireframe: boolean }).wireframe = wireframe
  }
  model.traverse((obj) => {
    if ('isMesh' in obj && obj.isMesh) setWire((obj as Mesh).material)
  })
}

export interface IfcViewerProps {
  /** IFC가 뷰어에 성공적으로 로드될 때마다 호출 (API 업로드용 동일 파일 참조) */
  onIfcFileReady?: (file: File | null) => void
  /** 파이프라인 fe_results(선택 스텝 합성) — 원본 모델 위에 샘플 노드 필드 포인트 오버랩 */
  feResultsOverlay?: FeResultsPayload | null
}

export function IfcViewer({ onIfcFileReady, feResultsOverlay = null }: IfcViewerProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<{
    scene: Scene
    camera: PerspectiveCamera
    renderer: WebGLRenderer
    controls: OrbitControls
    root: Group
    loader: IFCLoader
    raf: number
  } | null>(null)
  const modelRef = useRef<IfcViewerMesh | null>(null)
  const gridRef = useRef<GridHelper | null>(null)
  const overlayRef = useRef<Points | null>(null)
  const [status, setStatus] = useState<string>('IFC 파일을 끌어다 놓거나 선택하세요.')
  const [busy, setBusy] = useState(false)
  const [gridInfo, setGridInfo] = useState<{ sizeX: number; sizeZ: number; cellSize: number } | null>(null)
  const [wireframe, setWireframe] = useState(false)
  const [glReady, setGlReady] = useState(false)
  const [showFeOverlay, setShowFeOverlay] = useState(true)
  /** 0 = 참조 좌표만; >0 이면 변위×배율로 점 구름을 띄워 변형을 보기 쉽게 */
  const [feDeformScale, setFeDeformScale] = useState(0)
  /** true면 솔리드 뒤에 가리지 않고 항상 앞에 그림 */
  const [feOverlayOnTop, setFeOverlayOnTop] = useState(false)
  /** true면 점 크기 자동(보수적). false면 아래 픽셀 값 사용 */
  const [fePointSizeAuto, setFePointSizeAuto] = useState(true)
  /** 수동 점 크기 (Three PointsMaterial size, 대략 화면상 반경) */
  const [fePointSizePx, setFePointSizePx] = useState(4)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let cancelled = false

    const scene = new Scene()
    scene.background = new Color(0x1a1d23)

    const camera = new PerspectiveCamera(50, host.clientWidth / host.clientHeight, 0.01, 1e6)
    camera.position.set(8, 6, 10)

    const renderer = new WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(host.clientWidth, host.clientHeight)
    host.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    scene.add(new AmbientLight(0xffffff, 0.55))
    const key = new DirectionalLight(0xffffff, 0.95)
    key.position.set(4, 12, 8)
    scene.add(key)
    const fill = new DirectionalLight(0xb8c4ff, 0.35)
    fill.position.set(-6, 4, -4)
    scene.add(fill)

    const root = new Group()
    scene.add(root)

    const loader = new IFCLoader()
    const wasmBase = `${import.meta.env.BASE_URL}wasm/`

    const tick = () => {
      controls.update()
      renderer.render(scene, camera)
      const ctx = sceneRef.current
      if (ctx) ctx.raf = requestAnimationFrame(tick)
    }

    const ro = new ResizeObserver(() => {
      if (!hostRef.current) return
      const w = hostRef.current.clientWidth
      const h = hostRef.current.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    })
    ro.observe(host)

    void (async () => {
      try {
        await loader.ifcManager.setWasmPath(wasmBase)
      } catch (e: unknown) {
        console.error(e)
        if (!cancelled) {
          setStatus('WASM 경로 초기화 실패. npm install 후 public/wasm을 확인하세요.')
        }
        return
      }
      if (cancelled) return

      sceneRef.current = { scene, camera, renderer, controls, root, loader, raf: 0 }
      sceneRef.current.raf = requestAnimationFrame(tick)
      setGlReady(true)
    })()

    return () => {
      cancelled = true
      const ctx = sceneRef.current
      if (ctx && overlayRef.current) {
        ctx.root.remove(overlayRef.current)
        disposeFeResultsOverlayPoints(overlayRef.current)
        overlayRef.current = null
      }
      setGlReady(false)
      cancelAnimationFrame(sceneRef.current?.raf ?? 0)
      ro.disconnect()
      controls.dispose()
      renderer.dispose()
      if (renderer.domElement.parentElement === host) {
        host.removeChild(renderer.domElement)
      }
      sceneRef.current = null
    }
  }, [])

  useEffect(() => {
    const ctx = sceneRef.current
    if (!glReady) {
      if (ctx && overlayRef.current) {
        ctx.root.remove(overlayRef.current)
        disposeFeResultsOverlayPoints(overlayRef.current)
        overlayRef.current = null
      }
      return
    }
    if (!ctx) return
    if (overlayRef.current) {
      ctx.root.remove(overlayRef.current)
      disposeFeResultsOverlayPoints(overlayRef.current)
      overlayRef.current = null
    }
    if (!showFeOverlay) return
    const pts = createFeResultsOverlayPoints(feResultsOverlay, {
      deformScale: feDeformScale,
      depthTest: !feOverlayOnTop,
      ...(fePointSizeAuto ? {} : { pointSize: fePointSizePx }),
    })
    if (pts) {
      ctx.root.add(pts)
      overlayRef.current = pts
    }
  }, [
    glReady,
    feResultsOverlay,
    showFeOverlay,
    feDeformScale,
    feOverlayOnTop,
    fePointSizeAuto,
    fePointSizePx,
  ])

  const loadBuffer = useCallback(
    async (buffer: ArrayBuffer, label: string, sourceFile?: File) => {
      const ctx = sceneRef.current
      if (!ctx) {
        setStatus('뷰어가 아직 준비되지 않았습니다. WASM 로드가 끝난 뒤 다시 파일을 선택해 주세요.')
        return
      }
      setBusy(true)
      setStatus(`로딩 중… ${label}`)
      try {
        const wasmBase = `${import.meta.env.BASE_URL}wasm/`
        await ctx.loader.ifcManager.setWasmPath(wasmBase)
        if (modelRef.current) {
          const prev = modelRef.current
          ctx.root.remove(prev)
          prev.close()
          modelRef.current = null
          if (gridRef.current) {
            ctx.scene.remove(gridRef.current)
            gridRef.current.dispose()
            gridRef.current = null
          }
          setGridInfo(null)
        }
        const model = await ctx.loader.parse(buffer)
        const mPerIfcUnit = inferIfcLengthScaleToMeters(buffer)
        model.scale.setScalar(mPerIfcUnit)
        ctx.root.add(model)
        model.updateMatrixWorld(true)
        modelRef.current = model
        const info = updateFloorGrid(ctx.scene, ctx.root, gridRef)
        setGridInfo(info)
        setModelWireframe(model, wireframe)
        fitCameraToObject(ctx.camera, ctx.controls, ctx.root)
        setStatus(`표시 중: ${label}`)
        const f =
          sourceFile ?? new File([buffer], label, { type: 'application/octet-stream' })
        onIfcFileReady?.(f)
      } catch (e) {
        console.error(e)
        setStatus(e instanceof Error ? e.message : 'IFC 파싱 실패')
      } finally {
        setBusy(false)
      }
    },
    [onIfcFileReady, wireframe],
  )

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (!glReady) {
        setStatus('뷰어 준비 중입니다. 잠시 후 다시 끌어다 놓아 주세요.')
        return
      }
      const file = e.dataTransfer.files[0]
      if (!file?.name.toLowerCase().endsWith('.ifc')) {
        setStatus('.ifc 파일만 지원합니다.')
        return
      }
      void file.arrayBuffer().then((buf) => loadBuffer(buf, file.name, file))
    },
    [glReady, loadBuffer],
  )

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      void file.arrayBuffer().then((buf) => loadBuffer(buf, file.name, file))
      e.target.value = ''
    },
    [loadBuffer],
  )

  const toggleWireframe = useCallback(() => {
    const next = !wireframe
    setWireframe(next)
    const m = modelRef.current
    if (m) setModelWireframe(m, next)
  }, [wireframe])

  return (
    <div className="ifc-viewer">
      <div className="ifc-viewer__toolbar">
        <span className="ifc-viewer__status">
          {!glReady ? <span className="ifc-viewer__wasm-loading">WASM 로드 중…</span> : status}
        </span>
        {gridInfo ? (
          <span className="ifc-viewer__grid-label" title="바닥 격자 (미터법)">
            격자 {gridInfo.sizeX.toFixed(1)}m × {gridInfo.sizeZ.toFixed(1)}m (1칸={gridInfo.cellSize}m)
          </span>
        ) : null}
        {hasFePointCloudData(feResultsOverlay) ? (
          <div className="ifc-viewer__fe-overlay-tools" title="fe_results 샘플 노드 점 구름 (색: von Mises 또는 |변위|)">
            <label className="ifc-viewer__checkbox">
              <input
                type="checkbox"
                checked={showFeOverlay}
                onChange={() => setShowFeOverlay((v) => !v)}
              />
              점 구름
            </label>
            <label className="ifc-viewer__fe-deform">
              변위 과장 ×
              <input
                type="number"
                min={0}
                step={1}
                value={feDeformScale}
                onChange={(e) => setFeDeformScale(Math.max(0, Number(e.target.value) || 0))}
                disabled={!showFeOverlay}
                aria-label="변위 과장 배율"
              />
            </label>
            <label className="ifc-viewer__checkbox">
              <input
                type="checkbox"
                checked={feOverlayOnTop}
                onChange={() => setFeOverlayOnTop((v) => !v)}
                disabled={!showFeOverlay}
              />
              항상 앞
            </label>
            <label className="ifc-viewer__checkbox" title="끄면 아래 숫자(픽셀)로 점 크기 고정">
              <input
                type="checkbox"
                checked={fePointSizeAuto}
                onChange={() => setFePointSizeAuto((v) => !v)}
                disabled={!showFeOverlay}
              />
              점 크기 자동
            </label>
            <label className="ifc-viewer__fe-deform">
              점 크기
              <input
                type="number"
                min={FE_POINT_SIZE_MIN}
                max={FE_POINT_SIZE_MAX}
                step="any"
                value={fePointSizePx}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  setFePointSizePx(
                    Number.isFinite(v)
                      ? Math.max(FE_POINT_SIZE_MIN, Math.min(FE_POINT_SIZE_MAX, v))
                      : 4,
                  )
                }}
                disabled={!showFeOverlay || fePointSizeAuto}
                title={`${FE_POINT_SIZE_MIN} ~ ${FE_POINT_SIZE_MAX} (Three PointsMaterial.size)`}
                aria-label="점 구름 크기"
              />
            </label>
          </div>
        ) : null}
        <label className="ifc-viewer__checkbox">
          <input
            type="checkbox"
            checked={wireframe}
            onChange={toggleWireframe}
            disabled={!gridInfo}
          />
          와이어프레임
        </label>
        <label
          className={`ifc-viewer__file${busy || !glReady ? ' ifc-viewer__file--disabled' : ''}`}
          title={!glReady ? 'web-ifc WASM 로드 후 선택할 수 있습니다' : undefined}
        >
          <input type="file" accept=".ifc" disabled={busy || !glReady} onChange={onFileInput} />
          파일 선택
        </label>
      </div>
      <div
        ref={hostRef}
        className="ifc-viewer__canvas-host"
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
        }}
        onDrop={onDrop}
      />
    </div>
  )
}
