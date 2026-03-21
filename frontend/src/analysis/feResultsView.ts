/**
 * 다중 *STEP 응답에서 선택한 케이스의 변위·응력을 VTK·요약에 쓰기 위한 뷰 모델.
 * API 루트 필드는 마지막 스텝과 동일하지만, load_steps 가 있으면 인덱스로 덮어씁니다.
 */
import type { FeResultsPayload } from '../api/types'

export function feResultsAtLoadStep(
  fe: FeResultsPayload | null,
  stepIndex: number,
): FeResultsPayload | null {
  if (!fe) return null
  const steps = fe.load_steps
  if (!steps || steps.length === 0) return fe
  const i = Math.max(0, Math.min(stepIndex, steps.length - 1))
  const s = steps[i]
  return {
    ...fe,
    displacement: s.displacement ?? fe.displacement,
    stress: s.stress ?? fe.stress,
    magnitude: s.magnitude ?? fe.magnitude,
    n_nodes_total_disp: s.n_nodes_total_disp ?? fe.n_nodes_total_disp,
    n_nodes_total_stress: s.n_nodes_total_stress ?? fe.n_nodes_total_stress,
    n_nodes_in_sample: s.n_nodes_in_sample ?? fe.n_nodes_in_sample,
    downsample_note: s.downsample_note ?? fe.downsample_note,
  }
}
