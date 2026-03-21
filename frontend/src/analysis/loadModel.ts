/**
 * 하중·지지 도메인 모델 — API `analysis_spec` JSON 과 설계 문서의 공통 언어.
 * 상세: docs/LOAD-MODEL-AND-INP.md
 *
 * ## 백엔드(`backend/app/analysis/load_spec_v1.py`)와의 관계
 *
 * - **서버가 검증·해석하는 것:** `static_linear`, `load_cases`, `supports`(현재 `min_z`만),
 *   `loads` 중 `nodal_force` + `rule`(max_z_single_node | min_z_single_node) 또는 `explicit`,
 *   그리고 `surface_pressure` + `selection.kind == 'exterior'`(외곽면 등가 절점하중, 선택 `normal_max_tilt_deg`),
 *   선택 `combinations[]`(케이스별 계수 선형 중첩 → 추가 `*STEP`),
 *   `gravity`(등가 절점하중) + 선택 최상위 `material_density_kg_m3`(없으면 API `density_kg_m3`).
 * - **타입만 있고 서버 미구현:** 지지의 `max_z_band` 등.
 *   이들을 JSON에 넣으면 Pydantic extra 정책에 따라 무시되거나(ignore) 추후 버전에서 오류가 날 수 있음.
 *
 * UI: `components/AnalysisSpecForm.tsx` 폼에서 하중 케이스·조합·nodal_force·surface_pressure·gravity 행 편집;
 * 그 외 타입은 JSON 모드.
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
  /** 규칙(max/min z 한 노드) 또는 명시 `node_ids`(메시 노드 태그) */
  target:
    | { mode: 'rule'; rule: 'max_z_single_node' | 'min_z_single_node' }
    | { mode: 'explicit'; node_ids: readonly number[] }
  /** 전역 좌표계, N */
  components: Vec3
}

/** C3D4 체적 질량×가속도 → 등가 절점 `*CLOAD` (밀도는 `material_density_kg_m3` 또는 API `density_kg_m3`) */
export interface GravityLoadV1 {
  type: 'gravity'
  id: string
  case_id: string
  /** m/s² */
  acceleration: Vec3
}

/**
 * `selection.kind == 'exterior'`: C3D4 외곽 삼각면에 등가 `*CLOAD`.
 * `normal_max_tilt_deg`(선택): 법선과 전역 +Z 사이 각 θ에 대해 |θ−90°| ≤ 값인 면만 적용(수직 외벽 위주).
 */
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

/** 선형 조합: 케이스별 `*CLOAD` 에 계수를 곱해 합산한 추가 `*STEP` */
export interface LoadCombinationV1 {
  id: string
  name: string
  /** load_cases 의 case_id → 계수 (Resolver 선형 중첩) */
  factors: Readonly<Record<string, number>>
}

export interface AnalysisInputV1 {
  version: typeof ANALYSIS_INPUT_VERSION
  analysis_type: AnalysisTypeV1
  load_cases: readonly LoadCaseMetaV1[]
  supports: readonly SupportRuleV1[]
  loads: readonly PrimaryLoadV1[]
  combinations?: readonly LoadCombinationV1[]
  /** 중력 하중 시 밀도 [kg/m³]. 없으면 파이프라인 `density_kg_m3` 쿼리 기본값 */
  material_density_kg_m3?: number
}

/** 스파이크 bc_mode 문자열과의 대응 (마이그레이션·프리셋용) */
export type LegacyBcMode =
  | 'FIX_MIN_Z_LOAD_MAX_Z'
  | 'FIX_MIN_Y_LOAD_MAX_Y'
  | 'FIX_MIN_Z_LOAD_TOP_X'
  | 'FIX_MIN_Z_LOAD_TOP_Y'
