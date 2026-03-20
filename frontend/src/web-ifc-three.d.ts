import type { Loader, LoadingManager, Mesh, Object3D } from 'three'

type IfcViewerMesh = Mesh & { close: (scene?: Object3D) => void }

declare module 'web-ifc-three' {
  export class IFCLoader extends Loader {
    ifcManager: {
      setWasmPath(path: string): Promise<void>
      parse(buffer: ArrayBuffer): Promise<IfcViewerMesh>
    }
    parse(buffer: ArrayBuffer): Promise<IfcViewerMesh>
    constructor(manager?: LoadingManager)
  }
}
