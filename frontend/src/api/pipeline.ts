import { joinApiUrl } from '../config'
import type {
  AnalyzeResponse,
  JobCreatedResponse,
  JobStatusResponse,
  PipelineQueryParams,
} from './types'

function buildQuery(params: PipelineQueryParams): string {
  const q = new URLSearchParams({
    mesh_size: String(params.mesh_size),
    young: String(params.young),
    poisson: String(params.poisson),
    density_kg_m3: String(params.density_kg_m3),
    load_z: String(params.load_z),
    geometry_strategy: params.geometry_strategy,
  })
  if (!params.run_ccx) {
    q.set('run_ccx', 'false')
  }
  if (params.boundary_mode) {
    q.set('boundary_mode', params.boundary_mode)
  }
  if (params.first_product_only) {
    q.set('first_product_only', 'true')
  }
  if (params.partition_ifc_elsets) {
    q.set('partition_ifc_elsets', 'true')
  }
  return q.toString()
}

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const j: unknown = await res.json()
    if (j && typeof j === 'object' && 'detail' in j) {
      const d = (j as { detail: unknown }).detail
      if (typeof d === 'string') return d
      return JSON.stringify(d)
    }
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`
}

export function artifactDownloadUrl(apiBase: string, artifactPath: string): string {
  if (artifactPath.startsWith('http://') || artifactPath.startsWith('https://')) {
    return artifactPath
  }
  return joinApiUrl(apiBase, artifactPath)
}

export async function postAnalyze(
  apiBase: string,
  file: File,
  params: PipelineQueryParams,
  signal?: AbortSignal,
): Promise<AnalyzeResponse> {
  const fd = new FormData()
  fd.append('file', file)
  const spec = params.analysis_spec?.trim()
  if (spec) {
    fd.append('analysis_spec', spec)
  }
  const url = `${joinApiUrl(apiBase, '/api/v1/analyze')}?${buildQuery(params)}`
  const res = await fetch(url, { method: 'POST', body: fd, signal })
  if (!res.ok) {
    throw new Error(await readErrorDetail(res))
  }
  return res.json() as Promise<AnalyzeResponse>
}

export async function postJob(
  apiBase: string,
  file: File,
  params: PipelineQueryParams,
  signal?: AbortSignal,
): Promise<JobCreatedResponse> {
  const fd = new FormData()
  fd.append('file', file)
  const spec = params.analysis_spec?.trim()
  if (spec) {
    fd.append('analysis_spec', spec)
  }
  const url = `${joinApiUrl(apiBase, '/api/v1/jobs')}?${buildQuery(params)}`
  const res = await fetch(url, { method: 'POST', body: fd, signal })
  if (!res.ok) {
    throw new Error(await readErrorDetail(res))
  }
  return res.json() as Promise<JobCreatedResponse>
}

export async function getJobStatus(
  apiBase: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatusResponse> {
  const url = joinApiUrl(apiBase, `/api/v1/jobs/${jobId}`)
  const res = await fetch(url, { signal })
  if (!res.ok) {
    throw new Error(await readErrorDetail(res))
  }
  return res.json() as Promise<JobStatusResponse>
}

export const POLL_MS = 1500
/** 비동기 폴링 상한 — 파이프라인·Celery 기본 한도(24h)에 맞춤 */
export const MAX_WAIT_MS = 8 * 60 * 60 * 1000

/** 대기 시간 초과 시 job_id를 포함해 상태 재확인/계속 대기 가능하게 함 */
export class PollTimeoutError extends Error {
  readonly jobId: string
  constructor(message: string, jobId: string) {
    super(message)
    this.name = 'PollTimeoutError'
    this.jobId = jobId
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const t = window.setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      window.clearTimeout(t)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

export interface PollProgress {
  elapsedMs: number
  status: string
  pollHint?: string | null
}

/** 비동기 작업이 끝날 때까지 폴링. 완료/실패 `JobStatusResponse` 반환. */
export async function pollJobUntilDone(
  apiBase: string,
  jobId: string,
  signal?: AbortSignal,
  onProgress?: (p: PollProgress) => void,
): Promise<JobStatusResponse> {
  const started = Date.now()
  for (;;) {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    const elapsed = Date.now() - started
    if (elapsed > MAX_WAIT_MS) {
      throw new PollTimeoutError(
        `작업 대기 시간 초과 (${Math.round(MAX_WAIT_MS / 60_000)}분). 백엔드는 아직 실행 중일 수 있습니다.`,
        jobId,
      )
    }
    const st = await getJobStatus(apiBase, jobId, signal)
    onProgress?.({
      elapsedMs: elapsed,
      status: st.status,
      pollHint: st.poll_hint,
    })
    if (st.status === 'completed' || st.status === 'failed') {
      return st
    }
    await sleep(POLL_MS, signal)
  }
}

export function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  if (m > 0) return `${m}분 ${s % 60}초`
  return `${s}초`
}
