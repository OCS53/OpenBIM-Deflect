/**
 * 하중·지지 도메인 모델 — API `analysis_spec` JSON 과 설계 문서의 공통 언어.
 * 상세: docs/LOAD-MODEL-AND-INP.md
 *
 * ## 백엔드(`backend/app/analysis/load_spec_v1.py`)와의 관계
 *
 * - **서버가 검증·해석하는 것:** `static_linear`, `load_cases`, `supports`(현재 `min_z`만),
 *   `loads` 중 `nodal_force` + `rule`(max_z_single_node | min_z_single_node) 또는 `explicit`.
 * - **타입만 있고 서버 미구현:** `GravityLoadV1`, `SurfacePressureLoadV1`, 조합 `LoadCombinationV1`,
 *   지지의 `max_z_band` 등. 이들을 JSON에 넣으면 Pydantic extra 정책에 따라 무시되거나(ignore) 추후 버전에서 오류가 날 수 있음.
 *
 * UI: `components/AnalysisSpecForm.tsx` 가 위 **구현된** 부분만 행 편집으로 채움. 나머지는 JSON 모드.
 */

export const ANALYSIS_INPUT_VERSION = 1 as const

/** 정적 선형만 가정. 확장: modal_response_spectrum 등 */
export type AnalysisTypeV1 = 'static_linear'

export type Vec3 = readonly [number, number, number]

/** 지지: 노드 규칙 + 고정할 자유도 (1~6, 솔리드는 보통 1~3) */
export interface SupportRuleV1 {
  id: string
  /** 예: min_z, max_z_band, bbox_face_xmin */
  selection: { type: 'min_z' } | { type: 'max_z_band'; z0: number; z1: number }
  fixed_dofs: readonly number[]
}

/** 단일 노드력 (Resolver가 노드 ID를 채움) */
export interface NodalForceLoadV1 {
  type: 'nodal_force'
  id: string
  case_id: string
  /** Resolver 전: 규칙만. 후: 명시 id */
  target:
    | { mode: 'rule'; rule: 'max_z_single_node' | 'min_z_single_node' }
    | { mode: 'explicit'; node_ids: readonly number[] }
  /** 전역 좌표계, N */
  components: Vec3
}

/** 백엔드 미구현 (로드맵 3단계 이후 Resolver·Emitter) */
export interface GravityLoadV1 {
  type: 'gravity'
  id: string
  case_id: string
  /** m/s² */
  acceleration: Vec3
}

/** 백엔드 미구현 */
export interface SurfacePressureLoadV1 {
  type: 'surface_pressure'
  id: string
  case_id: string
  /** Pa */
  magnitude: number
  /** 외기 면 등 — Resolver가 면 집합으로 변환 */
  selection: { kind: 'exterior'; normal_max_tilt_deg?: number }
}

export type PrimaryLoadV1 = NodalForceLoadV1 | GravityLoadV1 | SurfacePressureLoadV1

export interface LoadCaseMetaV1 {
  id: string
  name: string
  /** DEAD, LIVE, WIND, SNOW, SEISMIC_EQUIVALENT 등 */
  category: string
}

/** 백엔드 미구현 */
export interface LoadCombinationV1 {
  id: string
  name: string
  /** case_id → 계수 */
  factors: Readonly<Record<string, number>>
}

export interface AnalysisInputV1 {
  version: typeof ANALYSIS_INPUT_VERSION
  analysis_type: AnalysisTypeV1
  load_cases: readonly LoadCaseMetaV1[]
  supports: readonly SupportRuleV1[]
  loads: readonly PrimaryLoadV1[]
  combinations?: readonly LoadCombinationV1[]
}

/** 스파이크 bc_mode 문자열과의 대응 (마이그레이션·프리셋용) */
export type LegacyBcMode =
  | 'FIX_MIN_Z_LOAD_MAX_Z'
  | 'FIX_MIN_Y_LOAD_MAX_Y'
  | 'FIX_MIN_Z_LOAD_TOP_X'
  | 'FIX_MIN_Z_LOAD_TOP_Y'
