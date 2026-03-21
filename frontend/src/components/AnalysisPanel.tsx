import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  artifactDownloadUrl,
  formatElapsed,
  getJobStatus,
  MAX_WAIT_MS,
  pollJobUntilDone,
  PollTimeoutError,
  postAnalyze,
  postJob,
} from '../api/pipeline'
import type {
  BoundaryModeOption,
  FeResultsPayload,
  GeometryStrategy,
  JobStatusResponse,
  PipelineQueryParams,
} from '../api/types'
import { feResultsAtLoadStep } from '../analysis/feResultsView'
import {
  AnalysisSpecForm,
  analysisInputV1FromForm,
  defaultAnalysisSpecFormModel,
  type AnalysisSpecFormModel,
} from './AnalysisSpecForm'
import { defaultApiBase } from '../config'
import { FeResultsVtkView } from './FeResultsVtkView'
import './AnalysisPanel.css'

/** 구조화 스펙: 폼(행 편집) 또는 원시 JSON */
type AnalysisSpecInputMode = 'none' | 'form' | 'json'

type RunMode = 'sync' | 'async'

/** UI 하중 케이스 → API boundary_mode (null = IFC Pset·서버 기본) */
type LoadCasePreset =
  | 'ifc_default'
  | 'dead_z'
  | 'wind_x'
  | 'wind_y'
  | 'seis_x'
  | 'seis_y'
  | 'min_y_max_y'

function boundaryModeFromPreset(p: LoadCasePreset): BoundaryModeOption | null {
  switch (p) {
    case 'ifc_default':
      return null
    case 'dead_z':
      return 'FIX_MIN_Z_LOAD_MAX_Z'
    case 'wind_x':
    case 'seis_x':
      return 'FIX_MIN_Z_LOAD_TOP_X'
    case 'wind_y':
    case 'seis_y':
      return 'FIX_MIN_Z_LOAD_TOP_Y'
    case 'min_y_max_y':
      return 'FIX_MIN_Y_LOAD_MAX_Y'
    default:
      return null
  }
}

export interface AnalysisResultState {
  jobId: string
  artifacts: { name: string; href: string }[]
  pipelineReport: Record<string, unknown> | null | undefined
  logTail: string | null | undefined
  feResults?: FeResultsPayload | null
  jobStatus?: JobStatusResponse['status']
  /** 대기 시간 초과 후 백엔드가 아직 실행 중일 수 있는 상태 */
  timeout?: boolean
}

interface AnalysisPanelProps {
  ifcFile: File | null
}

export function AnalysisPanel({ ifcFile }: AnalysisPanelProps) {
  const envBase = useMemo(() => defaultApiBase(), [])
  const [baseOverride, setBaseOverride] = useState('')
  const apiBase = (baseOverride.trim() || envBase).replace(/\/$/, '')

  const [mode, setMode] = useState<RunMode>('async')
  const [geomStrategy, setGeomStrategy] = useState<GeometryStrategy>('auto')
  const [runCcx, setRunCcx] = useState(true)
  const [loadPreset, setLoadPreset] = useState<LoadCasePreset>('ifc_default')
  const [loadN, setLoadN] = useState(10_000)
  const [firstProductOnly, setFirstProductOnly] = useState(false)
  const [meshSize, setMeshSize] = useState(0.25)
  const [young, setYoung] = useState(210_000)
  const [poisson, setPoisson] = useState(0.3)
  const [analysisSpecMode, setAnalysisSpecMode] = useState<AnalysisSpecInputMode>('none')
  const [analysisSpecForm, setAnalysisSpecForm] = useState<AnalysisSpecFormModel>(() =>
    defaultAnalysisSpecFormModel(),
  )
  /** `json` 모드 전용 원시 JSON */
  const [analysisSpecJson, setAnalysisSpecJson] = useState('')

  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<string>('')
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  const [pollHint, setPollHint] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResultState | null>(null)
  const [selectedFeStepIndex, setSelectedFeStepIndex] = useState(0)

  const abortRef = useRef<AbortController | null>(null)

  const builtAnalysisSpecObject = useMemo(
    () => (analysisSpecMode === 'form' ? analysisInputV1FromForm(analysisSpecForm) : null),
    [analysisSpecMode, analysisSpecForm],
  )

  const effectiveAnalysisSpecString = useMemo(() => {
    if (analysisSpecMode === 'none') return null
    if (analysisSpecMode === 'form') {
      return builtAnalysisSpecObject ? JSON.stringify(builtAnalysisSpecObject) : null
    }
    const t = analysisSpecJson.trim()
    return t || null
  }, [analysisSpecMode, builtAnalysisSpecObject, analysisSpecJson])

  const effectiveParams = useMemo(
    (): PipelineQueryParams => ({
      mesh_size: meshSize,
      young,
      poisson,
      load_z: loadN,
      geometry_strategy: geomStrategy,
      run_ccx: runCcx,
      boundary_mode: boundaryModeFromPreset(loadPreset),
      first_product_only: firstProductOnly,
      analysis_spec: effectiveAnalysisSpecString,
    }),
    [
      geomStrategy,
      runCcx,
      meshSize,
      young,
      poisson,
      loadN,
      loadPreset,
      firstProductOnly,
      effectiveAnalysisSpecString,
    ],
  )

  const feResultsView = useMemo(
    () => feResultsAtLoadStep(result?.feResults ?? null, selectedFeStepIndex),
    [result?.feResults, selectedFeStepIndex],
  )

  const lastFeJobIdRef = useRef<string | null>(null)
  useEffect(() => {
    const jid = result?.jobId
    if (!jid) return
    const steps = result?.feResults?.load_steps
    if (lastFeJobIdRef.current !== jid) {
      lastFeJobIdRef.current = jid
      if (steps && steps.length > 1) setSelectedFeStepIndex(steps.length - 1)
      else setSelectedFeStepIndex(0)
      return
    }
    if (steps && steps.length > 1) {
      setSelectedFeStepIndex((prev) => Math.min(Math.max(0, prev), steps.length - 1))
    } else if (!steps || steps.length <= 1) {
      setSelectedFeStepIndex(0)
    }
  }, [result?.jobId, result?.feResults])

  const canRun = Boolean(apiBase && ifcFile && !busy)

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  const applyFinalStatus = useCallback(
    (final: JobStatusResponse) => {
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
    },
    [apiBase],
  )

  const run = useCallback(async () => {
    if (!ifcFile || !apiBase) return
    stop()
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    setError(null)
    setResult(null)
    setElapsedMs(null)
    setPollHint(null)
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
        const final = await pollJobUntilDone(
          apiBase,
          created.job_id,
          ac.signal,
          (p) => {
            setElapsedMs(p.elapsedMs)
            if (p.pollHint) setPollHint(p.pollHint)
            const statusLabel = p.status === 'running' ? '실행 중' : p.status === 'pending' ? '대기 중' : p.status
            setPhase(`폴링… ${statusLabel} · ${formatElapsed(p.elapsedMs)} 경과`)
          },
        )
        applyFinalStatus(final)
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setPhase('취소됨')
      } else if (e instanceof PollTimeoutError) {
        setResult({
          jobId: e.jobId,
          artifacts: [],
          pipelineReport: null,
          logTail: null,
          jobStatus: 'running',
          timeout: true,
        })
        setPhase(`대기 시간 초과 (${Math.round(MAX_WAIT_MS / 60_000)}분)`)
        setError(e.message)
      } else {
        const msg = e instanceof Error ? e.message : String(e)
        const netHint =
          /failed to fetch|networkerror|load failed/i.test(msg)
            ? '\n\n브라우저·프록시가 장시간 연결을 끊었거나, 서버 PIPELINE_TIMEOUT_SEC 에 걸렸을 수 있습니다. 대형 모델은 비동기(POST /jobs)를 권장합니다.'
            : ''
        setError(msg + netHint)
        setPhase('오류')
      }
    } finally {
      setBusy(false)
      setElapsedMs(null)
      abortRef.current = null
    }
  }, [apiBase, ifcFile, mode, effectiveParams, stop, applyFinalStatus])

  const checkJobStatus = useCallback(async () => {
    const r = result
    if (!r?.timeout || !r.jobId || !apiBase) return
    setPhase('상태 확인 중…')
    try {
      const st = await getJobStatus(apiBase, r.jobId)
      if (st.status === 'completed' || st.status === 'failed') {
        setResult(null)
        applyFinalStatus(st)
      } else {
        setPhase(`아직 ${st.status === 'running' ? '실행 중' : '대기 중'}입니다.`)
        setError(null)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [result, apiBase, applyFinalStatus])

  const continueWaiting = useCallback(() => {
    const jobId = result?.timeout ? result.jobId : null
    if (!jobId) return
    setError(null)
    setPollHint(null)
    setResult(null)
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    setPhase(`계속 대기… (${jobId.slice(0, 8)}…)`)
    pollJobUntilDone(apiBase, jobId, ac.signal, (p) => {
      setElapsedMs(p.elapsedMs)
      if (p.pollHint) setPollHint(p.pollHint)
      setPhase(`폴링… ${p.status === 'running' ? '실행 중' : p.status} · ${formatElapsed(p.elapsedMs)}`)
    })
      .then(applyFinalStatus)
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') {
          setPhase('취소됨')
        } else if (e instanceof PollTimeoutError) {
          setResult({
            jobId: e.jobId,
            artifacts: [],
            pipelineReport: null,
            logTail: null,
            jobStatus: 'running',
            timeout: true,
          })
          setPhase(`대기 시간 초과 (${Math.round(MAX_WAIT_MS / 60_000)}분)`)
          setError(e.message)
        } else {
          setError(e instanceof Error ? e.message : String(e))
        }
      })
      .finally(() => {
        setBusy(false)
        setElapsedMs(null)
        abortRef.current = null
      })
  }, [result, apiBase, applyFinalStatus])

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

      <fieldset className="analysis-panel__fieldset">
        <legend>복합 구조물 · 하중 (MVP)</legend>
        <div className="analysis-panel__row analysis-panel__fieldset-row">
          <label className="analysis-panel__grow">
            하중 케이스
            <select
              value={loadPreset}
              onChange={(e) => setLoadPreset(e.target.value as LoadCasePreset)}
              aria-label="하중 케이스"
            >
              <option value="ifc_default">IFC / 서버 기본 (Pset 있으면 적용)</option>
              <option value="dead_z">중력 (−Z, 최소 Z 고정 · 최고 Z 노드)</option>
              <option value="wind_x">풍하중 +X (최소 Z 고정 · Z 최대 노드, dof 1)</option>
              <option value="wind_y">풍하중 +Y (최소 Z 고정 · Z 최대 노드, dof 2)</option>
              <option value="seis_x">지진 등가 정적 +X (풍과 동일 스텁)</option>
              <option value="seis_y">지진 등가 정적 +Y (풍과 동일 스텁)</option>
              <option value="min_y_max_y">최소 Y 고정 · 최대 Y 노드 (레거시 축)</option>
            </select>
          </label>
          <label>
            하중 [N]
            <input
              type="number"
              min={0}
              step={100}
              value={loadN}
              onChange={(e) => setLoadN(Number(e.target.value))}
              aria-label="하중 크기 뉴턴"
            />
          </label>
        </div>
        <p className="analysis-panel__fieldset-note">
          풍·지진은 <strong>단일 절점 등가하중</strong> 스텁입니다. 스펙트럼·조합·면하중은 솔버·메쉬 확장이 필요합니다.
        </p>
        <div className="analysis-panel__row">
          <label className="analysis-panel__check-wide">
            <input
              type="checkbox"
              checked={firstProductOnly}
              onChange={(e) => setFirstProductOnly(e.target.checked)}
            />
            단일 부재만 (첫 구조 요소) — 복합 모델 대신 단일 보·기둥 검증용
          </label>
        </div>
        <details className="analysis-panel__details">
          <summary>구조화 스펙 AnalysisInputV1 (선택)</summary>
          <p className="analysis-panel__fieldset-note">
            켜면 <code>boundary_mode</code>·쿼리 하중 대신 CalculiX INP 를 스펙으로 생성합니다. 샘플:{' '}
            <code>sample/analysis_input_v1_two_steps_example.json</code>.
          </p>
          <div className="analysis-panel__row analysis-panel__spec-modes">
            <span>입력 방식:</span>
            <label>
              <input
                type="radio"
                name="analysisSpecMode"
                checked={analysisSpecMode === 'none'}
                onChange={() => setAnalysisSpecMode('none')}
              />
              끔 (서버·Pset 기본)
            </label>
            <label>
              <input
                type="radio"
                name="analysisSpecMode"
                checked={analysisSpecMode === 'form'}
                onChange={() => setAnalysisSpecMode('form')}
              />
              폼 (케이스·노드력 행)
            </label>
            <label>
              <input
                type="radio"
                name="analysisSpecMode"
                checked={analysisSpecMode === 'json'}
                onChange={() => setAnalysisSpecMode('json')}
              />
              JSON (고급)
            </label>
          </div>
          {analysisSpecMode === 'form' ? (
            <>
              {builtAnalysisSpecObject ? null : (
                <p className="analysis-panel__warn">
                  케이스 id 가 비었거나 하중의 케이스 id 가 목록에 없으면 전송되지 않습니다.
                </p>
              )}
              <AnalysisSpecForm model={analysisSpecForm} onChange={setAnalysisSpecForm} />
            </>
          ) : null}
          {analysisSpecMode === 'json' ? (
            <label className="analysis-panel__grow analysis-panel__textarea-label">
              <textarea
                className="analysis-panel__textarea"
                rows={8}
                spellCheck={false}
                placeholder='{"version":1,"analysis_type":"static_linear",...}'
                value={analysisSpecJson}
                onChange={(e) => setAnalysisSpecJson(e.target.value)}
                aria-label="AnalysisInputV1 JSON"
              />
            </label>
          ) : null}
        </details>
        <details className="analysis-panel__details">
          <summary>재료 · 메쉬 (고급)</summary>
          <div className="analysis-panel__row analysis-panel__fieldset-row">
            <label>
              mesh_size
              <input
                type="number"
                min={0.001}
                step={0.01}
                value={meshSize}
                onChange={(e) => setMeshSize(Number(e.target.value))}
              />
            </label>
            <label>
              young
              <input
                type="number"
                min={1}
                step={1000}
                value={young}
                onChange={(e) => setYoung(Number(e.target.value))}
              />
            </label>
            <label>
              poisson
              <input
                type="number"
                min={0}
                max={0.499}
                step={0.01}
                value={poisson}
                onChange={(e) => setPoisson(Number(e.target.value))}
              />
            </label>
          </div>
        </details>
      </fieldset>

      <div className="analysis-panel__row analysis-panel__actions">
        <button type="button" disabled={!canRun} onClick={() => void run()}>
          파이프라인 실행
        </button>
        <button type="button" disabled={!busy} onClick={stop}>
          중단
        </button>
        {phase ? <span className="analysis-panel__status">{phase}</span> : null}
        {elapsedMs != null ? (
          <span className="analysis-panel__elapsed">{formatElapsed(elapsedMs)}</span>
        ) : null}
        {!ifcFile ? (
          <span className="analysis-panel__status">먼저 IFC를 뷰어에 올려 주세요.</span>
        ) : null}
      </div>
      {mode === 'async' && !busy ? (
        <p className="analysis-panel__hint">
          예상: 대형 모델(10층+ 슬래브)은 1시간 이상 걸릴 수 있습니다. 폴링 최대 약 {Math.round(MAX_WAIT_MS / 60_000)}분.
          비동기 작업은 Celery worker 가 필요합니다. <code>docker compose up api</code> 는 worker 를 함께 띄웁니다.
        </p>
      ) : null}
      {mode === 'sync' && !busy ? (
        <p className="analysis-panel__hint analysis-panel__hint--warn">
          동기 <code>/analyze</code> 는 탭을 닫지 말고 기다려야 합니다. 서버는{' '}
          <code>PIPELINE_TIMEOUT_SEC</code>(기본 24h) 후 하위 프로세스를 중단합니다. 예전 기본 1h 에서 끊겼다면 API
          이미지를 다시 빌드하거나 환경 변수를 늘리세요. 1시간 이상 예상되면 <strong>비동기</strong> 사용을 권장합니다.
        </p>
      ) : null}
      {pollHint ? <div className="analysis-panel__poll-hint">{pollHint}</div> : null}

      {error ? <div className="analysis-panel__err">{error}</div> : null}
      {result?.timeout ? (
        <div className="analysis-panel__timeout-actions">
          <button type="button" onClick={() => void checkJobStatus()}>
            상태 확인
          </button>
          <button type="button" onClick={continueWaiting}>
            계속 대기
          </button>
        </div>
      ) : null}

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
              {feResultsView?.magnitude ? (
                <ul className="analysis-panel__fe-mag">
                  {feResultsView.magnitude.max_abs_displacement != null ? (
                    <li>
                      max |변위|: {feResultsView.magnitude.max_abs_displacement.toExponential(4)}
                    </li>
                  ) : null}
                  {feResultsView.magnitude.max_von_mises != null ? (
                    <li>
                      max von Mises: {feResultsView.magnitude.max_von_mises.toExponential(4)}
                    </li>
                  ) : null}
                </ul>
              ) : null}
              {feResultsView?.downsample_note ? (
                <p className="analysis-panel__status">{feResultsView.downsample_note}</p>
              ) : null}
              {result.feResults.load_steps && result.feResults.load_steps.length > 1 ? (
                <div className="analysis-panel__row analysis-panel__fe-step">
                  <label>
                    케이스 스텝 (VTK·위 요약)
                    <select
                      value={selectedFeStepIndex}
                      onChange={(e) => setSelectedFeStepIndex(Number(e.target.value))}
                      aria-label="FRD load step"
                    >
                      {result.feResults.load_steps.map((s, i) => (
                        <option key={`${s.step_index}-${i}`} value={i}>
                          #{s.step_index} {s.case_id || ''}
                          {s.name ? ` — ${s.name}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : null}
              <FeResultsVtkView feResults={feResultsView} />
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
