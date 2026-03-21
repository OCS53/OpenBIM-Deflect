import { useState } from 'react'
import type { FeResultsPayload } from './api/types'
import { AnalysisPanel } from './components/AnalysisPanel'
import { IfcViewer } from './components/IfcViewer'
import './App.css'

function App() {
  const [ifcFile, setIfcFile] = useState<File | null>(null)
  const [feResultsOverlay, setFeResultsOverlay] = useState<FeResultsPayload | null>(null)

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">OpenBIM-Deflect · IFC 뷰어</h1>
        <p className="app__subtitle">
          로컬 .ifc 미리보기 (web-ifc-three) · 백엔드 파이프라인은{' '}
          <code className="app__code">VITE_API_URL</code> 설정 후 실행
        </p>
      </header>
      <main className="app__main">
        <AnalysisPanel ifcFile={ifcFile} onFeResultsOverlay={setFeResultsOverlay} />
        <div className="app__viewer-wrap">
          <IfcViewer onIfcFileReady={setIfcFile} feResultsOverlay={feResultsOverlay} />
        </div>
      </main>
    </div>
  )
}

export default App
