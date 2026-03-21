export type GeometryStrategy = 'auto' | 'stl_classify' | 'stl_raw' | 'occ_bbox'

/** CalculiX 스텁 경계·하중 (IFC OpenBIM_Deflect BoundaryMode / API boundary_mode) */
export type BoundaryModeOption =
  | 'FIX_MIN_Z_LOAD_MAX_Z'
  | 'FIX_MIN_Y_LOAD_MAX_Y'
  | 'FIX_MIN_Z_LOAD_TOP_X'
  | 'FIX_MIN_Z_LOAD_TOP_Y'

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
  /** 참조 형상 좌표 (INP *NODE, VTK 등) */
  x?: number[]
  y?: number[]
  z?: number[]
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

/** 다중 CalculiX *STEP 시 FRD 블록 순서와 대응 */
export interface FeResultsLoadStep {
  step_index: number
  case_id?: string
  name?: string
  displacement?: FeDisplacementBlock | null
  stress?: FeStressBlock | null
  magnitude?: FeResultsMagnitude | null
  n_nodes_total_disp?: number | null
  n_nodes_total_stress?: number | null
  n_nodes_in_sample?: number | null
  downsample_note?: string | null
}

export interface FeResultsPayload {
  version?: 1
  source?: string
  frd_basename?: string
  parse_error?: string | null
  n_steps_in_frd?: number | null
  n_nodes_total_disp?: number | null
  n_nodes_total_stress?: number | null
  n_nodes_in_sample?: number | null
  downsample_note?: string | null
  displacement?: FeDisplacementBlock | null
  stress?: FeStressBlock | null
  magnitude?: FeResultsMagnitude | null
  /** 루트 displacement 등은 마지막 스텝과 동일 (VTK 호환) */
  load_steps?: FeResultsLoadStep[] | null
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
  poll_hint?: string | null
  /** 제출된 AnalysisInputV1 사용 여부 (job_status 스냅샷) */
  analysis_spec_used?: boolean | null
}

export interface PipelineQueryParams {
  mesh_size: number
  young: number
  poisson: number
  load_z: number
  run_ccx: boolean
  geometry_strategy: GeometryStrategy
  /** 미지정 시 IFC Pset·파이프라인 기본 */
  boundary_mode?: BoundaryModeOption | null
  /** true 이면 구조 부재 중 첫 요소만 (단일 부재 검증) */
  first_product_only?: boolean
  /**
   * AnalysisInputV1 JSON 문자열 (multipart `analysis_spec`). 빈 문자열·미지정이면 서버 기본 경계/하중.
   * @see docs/LOAD-MODEL-AND-INP.md
   */
  analysis_spec?: string | null
}
