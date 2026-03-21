import { useEffect, useRef } from 'react'
import type { FeResultsPayload } from '../api/types'
import './FeResultsVtkView.css'

/** VTK.js: 샘플 노드 위치 + von Mises 또는 |변위| 스칼라 포인트 가시화 */
export function FeResultsVtkView({ feResults }: { feResults: FeResultsPayload | null }) {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host || !feResults?.displacement) return
    const d = feResults.displacement
    if (!d.x?.length || d.x.length !== d.node_id.length) {
      return
    }

    let cancelled = false
    const run = async () => {
      await import('@kitware/vtk.js/Rendering/Profiles/Geometry')

      const vtkActor = (await import('@kitware/vtk.js/Rendering/Core/Actor')).default
      const vtkDataArray = (await import('@kitware/vtk.js/Common/Core/DataArray')).default
      const vtkMapper = (await import('@kitware/vtk.js/Rendering/Core/Mapper')).default
      const vtkOpenGLRenderWindow = (await import('@kitware/vtk.js/Rendering/OpenGL/RenderWindow'))
        .default
      const vtkPoints = (await import('@kitware/vtk.js/Common/Core/Points')).default
      const vtkPolyData = (await import('@kitware/vtk.js/Common/DataModel/PolyData')).default
      const vtkRenderWindow = (await import('@kitware/vtk.js/Rendering/Core/RenderWindow')).default
      const vtkRenderWindowInteractor = (await import('@kitware/vtk.js/Rendering/Core/RenderWindowInteractor'))
        .default
      const vtkRenderer = (await import('@kitware/vtk.js/Rendering/Core/Renderer')).default
      const vtkInteractorStyleTrackballCamera = (
        await import('@kitware/vtk.js/Interaction/Style/InteractorStyleTrackballCamera')
      ).default

      if (cancelled || !hostRef.current) return

      const n = d.node_id.length
      const points = vtkPoints.newInstance()
      for (let i = 0; i < n; i++) {
        points.insertNextPoint(d.x![i], d.y![i], d.z![i])
      }
      const poly = vtkPolyData.newInstance()
      poly.setPoints(points)
      const verts = poly.getVerts()
      for (let i = 0; i < n; i++) {
        verts.insertNextCell([i])
      }

      const stress = feResults.stress
      const scalars = new Float32Array(n)
      if (stress?.von_mises?.length && stress.node_id.length) {
        const map = new Map<number, number>()
        for (let i = 0; i < stress.node_id.length; i++) {
          map.set(stress.node_id[i], stress.von_mises[i])
        }
        for (let i = 0; i < n; i++) {
          scalars[i] = map.get(d.node_id[i]) ?? 0
        }
      } else {
        for (let i = 0; i < n; i++) {
          scalars[i] = Math.hypot(d.ux[i], d.uy[i], d.uz[i])
        }
      }

      const da = vtkDataArray.newInstance({
        name: 'S',
        values: scalars,
      })
      poly.getPointData().setScalars(da)

      const mapper = vtkMapper.newInstance()
      mapper.setInputData(poly)
      mapper.setScalarModeToUsePointData()
      mapper.setColorByArrayName('S')
      mapper.setScalarVisibility(true)

      const actor = vtkActor.newInstance()
      actor.setMapper(mapper)

      const renderWindow = vtkRenderWindow.newInstance()
      const renderer = vtkRenderer.newInstance({ background: [0.1, 0.11, 0.14] })
      renderWindow.addRenderer(renderer)
      const glWindow = vtkOpenGLRenderWindow.newInstance()
      glWindow.setContainer(host)
      renderWindow.addView(glWindow)
      renderer.addActor(actor)
      renderer.resetCamera()

      const interactor = vtkRenderWindowInteractor.newInstance()
      interactor.setView(glWindow)
      interactor.initialize()
      interactor.bindEvents(host)
      interactor.setInteractorStyle(vtkInteractorStyleTrackballCamera.newInstance())

      const ro = new ResizeObserver(() => {
        if (!hostRef.current) return
        const { width, height } = hostRef.current.getBoundingClientRect()
        glWindow.setSize(Math.max(1, width), Math.max(1, height))
        renderWindow.render()
      })
      ro.observe(host)
      glWindow.setSize(host.clientWidth || 400, host.clientHeight || 280)
      renderWindow.render()

      return () => {
        ro.disconnect()
        interactor.unbindEvents()
        interactor.delete()
        glWindow.delete()
        renderWindow.delete()
        actor.delete()
        mapper.delete()
        poly.delete()
        points.delete()
      }
    }

    let cleanup: (() => void) | undefined
    void run().then((fn) => {
      cleanup = fn
    })

    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [feResults]) // 부모가 스텝별 displacement·stress 를 합성한 객체를 넘김

  if (!feResults?.displacement?.x?.length) {
    return (
      <div className="fe-vtk fe-vtk--empty">
        완료된 해석에 노드 좌표(x,y,z)가 포함된 <code>fe_results</code> 가 있으면 VTK 포인트 필드가 표시됩니다.
      </div>
    )
  }

  return (
    <div className="fe-vtk">
      <div className="fe-vtk__title">VTK 결과 필드 (샘플 노드)</div>
      <div ref={hostRef} className="fe-vtk__canvas" />
    </div>
  )
}
