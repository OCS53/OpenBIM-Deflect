import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AmbientLight,
  Box3,
  Color,
  DirectionalLight,
  Group,
  type Mesh,
  Object3D,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { IFCLoader } from 'web-ifc-three'
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

export interface IfcViewerProps {
  /** IFC가 뷰어에 성공적으로 로드될 때마다 호출 (API 업로드용 동일 파일 참조) */
  onIfcFileReady?: (file: File | null) => void
}

export function IfcViewer({ onIfcFileReady }: IfcViewerProps) {
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
  const [status, setStatus] = useState<string>('IFC 파일을 끌어다 놓거나 선택하세요.')
  const [busy, setBusy] = useState(false)

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
    void loader.ifcManager.setWasmPath(wasmBase).catch((e: unknown) => {
      console.error(e)
      if (!cancelled) {
        setStatus('WASM 경로 초기화 실패. npm install 후 public/wasm을 확인하세요.')
      }
    })

    const tick = () => {
      controls.update()
      renderer.render(scene, camera)
      sceneRef.current!.raf = requestAnimationFrame(tick)
    }
    sceneRef.current = { scene, camera, renderer, controls, root, loader, raf: 0 }
    sceneRef.current.raf = requestAnimationFrame(tick)

    const ro = new ResizeObserver(() => {
      if (!hostRef.current) return
      const w = hostRef.current.clientWidth
      const h = hostRef.current.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    })
    ro.observe(host)

    return () => {
      cancelled = true
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

  const loadBuffer = useCallback(
    async (buffer: ArrayBuffer, label: string, sourceFile?: File) => {
      const ctx = sceneRef.current
      if (!ctx) return
      setBusy(true)
      setStatus(`로딩 중… ${label}`)
      try {
        if (modelRef.current) {
          const prev = modelRef.current
          ctx.root.remove(prev)
          prev.close()
          modelRef.current = null
        }
        const model = await ctx.loader.parse(buffer)
        ctx.root.add(model)
        modelRef.current = model
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
    [onIfcFileReady],
  )

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const file = e.dataTransfer.files[0]
      if (!file?.name.toLowerCase().endsWith('.ifc')) {
        setStatus('.ifc 파일만 지원합니다.')
        return
      }
      void file.arrayBuffer().then((buf) => loadBuffer(buf, file.name, file))
    },
    [loadBuffer],
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

  return (
    <div className="ifc-viewer">
      <div className="ifc-viewer__toolbar">
        <span className="ifc-viewer__status">{status}</span>
        <label className={`ifc-viewer__file${busy ? ' ifc-viewer__file--disabled' : ''}`}>
          <input type="file" accept=".ifc" disabled={busy} onChange={onFileInput} />
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
