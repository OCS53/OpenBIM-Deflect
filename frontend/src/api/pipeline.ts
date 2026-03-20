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
    load_z: String(params.load_z),
    geometry_strategy: params.geometry_strategy,
  })
  if (!params.run_ccx) {
    q.set('run_ccx', 'false')
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

const POLL_MS = 1500
const MAX_WAIT_MS = 55 * 60 * 1000

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

/** 비동기 작업이 끝날 때까지 폴링. 완료/실패 `JobStatusResponse` 반환. */
export async function pollJobUntilDone(
  apiBase: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatusResponse> {
  const started = Date.now()
  for (;;) {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    if (Date.now() - started > MAX_WAIT_MS) {
      throw new Error('작업 대기 시간 초과')
    }
    const st = await getJobStatus(apiBase, jobId, signal)
    if (st.status === 'completed' || st.status === 'failed') {
      return st
    }
    await sleep(POLL_MS, signal)
  }
}
