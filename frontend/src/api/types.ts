export type GeometryStrategy = 'auto' | 'stl_classify' | 'stl_raw' | 'occ_bbox'

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ArtifactInfo {
  name: string
  size_bytes: number
  url: string
}

export interface JobErrorDetail {
  message: string
  log_tail?: string | null
}

export interface FeDisplacementBlock {
  node_id: number[]
  ux: number[]
  uy: number[]
  uz: number[]
}

export interface FeStressBlock {
  node_id: number[]
  sxx: number[]
  syy: number[]
  szz: number[]
  sxy: number[]
  syz: number[]
  szx: number[]
  von_mises: number[]
}

export interface FeResultsMagnitude {
  max_abs_displacement?: number | null
  max_von_mises?: number | null
}

export interface FeResultsPayload {
  version?: 1
  source?: string
  frd_basename?: string
  parse_error?: string | null
  n_nodes_total_disp?: number | null
  n_nodes_total_stress?: number | null
  n_nodes_in_sample?: number | null
  downsample_note?: string | null
  displacement?: FeDisplacementBlock | null
  stress?: FeStressBlock | null
  magnitude?: FeResultsMagnitude | null
}

export interface AnalyzeResponse {
  job_id: string
  status: 'completed'
  artifacts: ArtifactInfo[]
  pipeline_report?: Record<string, unknown> | null
  log_tail?: string | null
  fe_results?: FeResultsPayload | null
}

export interface JobCreatedResponse {
  job_id: string
  status: 'pending'
  poll_url: string
}

export interface JobStatusResponse {
  job_id: string
  status: JobStatus
  artifacts?: ArtifactInfo[] | null
  pipeline_report?: Record<string, unknown> | null
  log_tail?: string | null
  fe_results?: FeResultsPayload | null
  error?: JobErrorDetail | null
  celery_task_id?: string | null
}

export interface PipelineQueryParams {
  mesh_size: number
  young: number
  poisson: number
  load_z: number
  run_ccx: boolean
  geometry_strategy: GeometryStrategy
}
