/// <reference types="vite/client" />

declare module '@kitware/vtk.js/*' {
  const mod: unknown
  export default mod
}

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
}
