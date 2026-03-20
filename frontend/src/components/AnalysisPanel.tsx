import { useCallback, useMemo, useRef, useState } from 'react'
import {
  artifactDownloadUrl,
  pollJobUntilDone,
  postAnalyze,
  postJob,
} from '../api/pipeline'
import type {
  FeResultsPayload,
  GeometryStrategy,
  JobStatusResponse,
  PipelineQueryParams,
} from '../api/types'
import { defaultApiBase } from '../config'
import './AnalysisPanel.css'

type RunMode = 'sync' | 'async'

export interface AnalysisResultState {
  jobId: string
  artifacts: { name: string; href: string }[]
  pipelineReport: Record<string, unknown> | null | undefined
  logTail: string | null | undefined
  feResults?: FeResultsPayload | null
  jobStatus?: JobStatusResponse['status']
}

interface AnalysisPanelProps {
  ifcFile: File | null
}

const defaultParams: PipelineQueryParams = {
  mesh_size: 120,
  young: 210_000,
  poisson: 0.3,
  load_z: 10_000,
  run_ccx: true,
  geometry_strategy: 'auto',
}

export function AnalysisPanel({ ifcFile }: AnalysisPanelProps) {
  const envBase = useMemo(() => defaultApiBase(), [])
  const [baseOverride, setBaseOverride] = useState('')
  const apiBase = (baseOverride.trim() || envBase).replace(/\/$/, '')

  const [mode, setMode] = useState<RunMode>('async')
  const [geomStrategy, setGeomStrategy] = useState<GeometryStrategy>('auto')
  const [runCcx, setRunCcx] = useState(true)

  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResultState | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const effectiveParams = useMemo(
    (): PipelineQueryParams => ({
      ...defaultParams,
      geometry_strategy: geomStrategy,
      run_ccx: runCcx,
    }),
    [geomStrategy, runCcx],
  )

  const canRun = Boolean(apiBase && ifcFile && !busy)

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  const run = useCallback(async () => {
    if (!ifcFile || !apiBase) return
    stop()
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    setError(null)
    setResult(null)
    setPhase(mode === 'sync' ? '동기 파이프라인 실행 중…' : '작업 등록 중…')

    try {
      if (mode === 'sync') {
        const data = await postAnalyze(apiBase, ifcFile, effectiveParams, ac.signal)
        setResult({
          jobId: data.job_id,
          artifacts: data.artifacts.map((a) => ({
            name: a.name,
            href: artifactDownloadUrl(apiBase, a.url),
          })),
          pipelineReport: data.pipeline_report,
          logTail: data.log_tail,
          feResults: data.fe_results,
          jobStatus: 'completed',
        })
        setPhase('완료')
      } else {
        const created = await postJob(apiBase, ifcFile, effectiveParams, ac.signal)
        setPhase(`폴링 중… (${created.job_id.slice(0, 8)}…)`)
        const final = await pollJobUntilDone(apiBase, created.job_id, ac.signal)
        if (final.status === 'failed') {
          const msg = final.error?.message ?? '파이프라인 실패'
          const tail = final.error?.log_tail
          setError(tail ? `${msg}\n\n--- log ---\n${tail}` : msg)
          setResult({
            jobId: final.job_id,
            artifacts: [],
            pipelineReport: final.pipeline_report,
            logTail: final.log_tail,
            feResults: final.fe_results,
            jobStatus: 'failed',
          })
          setPhase('실패')
        } else {
          const arts = final.artifacts ?? []
          setResult({
            jobId: final.job_id,
            artifacts: arts.map((a) => ({
              name: a.name,
              href: artifactDownloadUrl(apiBase, a.url),
            })),
            pipelineReport: final.pipeline_report,
            logTail: final.log_tail,
            feResults: final.fe_results,
            jobStatus: 'completed',
          })
          setPhase('완료')
        }
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setPhase('취소됨')
      } else {
        setError(e instanceof Error ? e.message : String(e))
        setPhase('오류')
      }
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }, [apiBase, ifcFile, mode, effectiveParams, stop])

  return (
    <section className="analysis-panel" aria-label="백엔드 파이프라인">
      <div className="analysis-panel__row">
        <label>
          API base
          <input
            className="analysis-panel__base"
            type="text"
            placeholder={envBase || 'http://localhost:8000'}
            value={baseOverride}
            onChange={(e) => setBaseOverride(e.target.value)}
            aria-label="API base URL 오버라이드"
          />
        </label>
        {!envBase && !baseOverride.trim() ? (
          <span className="analysis-panel__warn">
            `.env`에 `VITE_API_URL` 이 없습니다. 위에 URL을 입력하세요.
          </span>
        ) : null}
      </div>

      <div className="analysis-panel__row">
        <span>실행 방식:</span>
        <label>
          <input
            type="radio"
            name="runMode"
            checked={mode === 'async'}
            onChange={() => setMode('async')}
          />
          비동기 (POST /jobs + 폴링)
        </label>
        <label>
          <input
            type="radio"
            name="runMode"
            checked={mode === 'sync'}
            onChange={() => setMode('sync')}
          />
          동기 (POST /analyze)
        </label>
        <label>
          <input
            type="checkbox"
            checked={runCcx}
            onChange={(e) => setRunCcx(e.target.checked)}
          />
          CalculiX 실행
        </label>
        <label>
          geometry
          <select
            value={geomStrategy}
            onChange={(e) => setGeomStrategy(e.target.value as GeometryStrategy)}
          >
            <option value="auto">auto</option>
            <option value="stl_classify">stl_classify</option>
            <option value="stl_raw">stl_raw</option>
            <option value="occ_bbox">occ_bbox</option>
          </select>
        </label>
      </div>

      <div className="analysis-panel__row analysis-panel__actions">
        <button type="button" disabled={!canRun} onClick={() => void run()}>
          파이프라인 실행
        </button>
        <button type="button" disabled={!busy} onClick={stop}>
          중단
        </button>
        {phase ? <span className="analysis-panel__status">{phase}</span> : null}
        {!ifcFile ? (
          <span className="analysis-panel__status">먼저 IFC를 뷰어에 올려 주세요.</span>
        ) : null}
      </div>

      {error ? <div className="analysis-panel__err">{error}</div> : null}

      {result ? (
        <div className="analysis-panel__results">
          <h3>Job {result.jobId}</h3>
          {result.artifacts.length > 0 ? (
            <>
              <h3>산출물 다운로드</h3>
              <div className="analysis-panel__artifacts">
                {result.artifacts.map((a) => (
                  <a key={a.name} href={a.href} download={a.name} target="_blank" rel="noreferrer">
                    {a.name}
                  </a>
                ))}
              </div>
            </>
          ) : null}
          {result.feResults ? (
            <>
              <h3>fe_results (FRD 요약)</h3>
              {result.feResults.parse_error ? (
                <p className="analysis-panel__warn">{result.feResults.parse_error}</p>
              ) : null}
              {result.feResults.magnitude ? (
                <ul className="analysis-panel__fe-mag">
                  {result.feResults.magnitude.max_abs_displacement != null ? (
                    <li>
                      max |변위|: {result.feResults.magnitude.max_abs_displacement.toExponential(4)}
                    </li>
                  ) : null}
                  {result.feResults.magnitude.max_von_mises != null ? (
                    <li>
                      max von Mises: {result.feResults.magnitude.max_von_mises.toExponential(4)}
                    </li>
                  ) : null}
                </ul>
              ) : null}
              {result.feResults.downsample_note ? (
                <p className="analysis-panel__status">{result.feResults.downsample_note}</p>
              ) : null}
              <details>
                <summary>전체 JSON</summary>
                <pre>{JSON.stringify(result.feResults, null, 2)}</pre>
              </details>
            </>
          ) : null}
          {result.pipelineReport && Object.keys(result.pipelineReport).length > 0 ? (
            <>
              <h3>pipeline_report</h3>
              <pre>{JSON.stringify(result.pipelineReport, null, 2)}</pre>
            </>
          ) : null}
          {result.logTail ? (
            <>
              <h3>log (tail)</h3>
              <pre>{result.logTail}</pre>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
