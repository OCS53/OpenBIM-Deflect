/**
 * AnalysisInputV1 MVP 폼 — nodal_force + min_z 지지만 (백엔드 load_spec_v1 와 동일 범위).
 * @see docs/LOAD-MODEL-AND-INP.md
 */
import './AnalysisSpecForm.css'

export type NodalRule = 'max_z_single_node' | 'min_z_single_node'

export interface LoadCaseFormRow {
  id: string
  name: string
  category: string
}

export interface NodalLoadFormRow {
  id: string
  caseId: string
  rule: NodalRule
  fx: number
  fy: number
  fz: number
}

export interface AnalysisSpecFormModel {
  loadCases: LoadCaseFormRow[]
  loads: NodalLoadFormRow[]
}

export function defaultAnalysisSpecFormModel(): AnalysisSpecFormModel {
  return {
    loadCases: [{ id: 'LC1', name: '', category: 'GENERAL' }],
    loads: [
      { id: 'N1', caseId: 'LC1', rule: 'max_z_single_node', fx: 0, fy: 0, fz: -10_000 },
    ],
  }
}

/** 폼 → API JSON 객체 (version 1). 유효하지 않으면 null */
export function analysisInputV1FromForm(model: AnalysisSpecFormModel): Record<string, unknown> | null {
  const ids = model.loadCases.map((c) => c.id.trim()).filter(Boolean)
  if (ids.length === 0 || new Set(ids).size !== ids.length) return null
  if (model.loads.length === 0) return null
  for (const L of model.loads) {
    if (!L.caseId.trim() || !ids.includes(L.caseId.trim())) return null
  }
  return {
    version: 1,
    analysis_type: 'static_linear',
    load_cases: model.loadCases.map((c) => ({
      id: c.id.trim(),
      name: c.name.trim(),
      category: c.category.trim() || 'GENERAL',
    })),
    supports: [
      {
        id: 'fix_min_z',
        selection: { type: 'min_z' },
        fixed_dofs: [1, 2, 3],
      },
    ],
    loads: model.loads.map((L) => ({
      type: 'nodal_force',
      id: L.id.trim() || `N_${L.caseId}`,
      case_id: L.caseId.trim(),
      target: { mode: 'rule', rule: L.rule },
      components: [L.fx, L.fy, L.fz],
    })),
  }
}

function uid(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`
}

interface AnalysisSpecFormProps {
  model: AnalysisSpecFormModel
  onChange: (m: AnalysisSpecFormModel) => void
}

export function AnalysisSpecForm({ model, onChange }: AnalysisSpecFormProps) {
  const setCases = (loadCases: LoadCaseFormRow[]) => onChange({ ...model, loadCases })
  const setLoads = (loads: NodalLoadFormRow[]) => onChange({ ...model, loads })

  const addCase = () => {
    const n = model.loadCases.length + 1
    setCases([...model.loadCases, { id: `LC${n}`, name: '', category: 'GENERAL' }])
  }
  const removeCase = (idx: number) => {
    const removed = model.loadCases[idx]?.id
    const next = model.loadCases.filter((_, i) => i !== idx)
    if (next.length === 0) return
    const nextLoads = model.loads.map((L) =>
      L.caseId === removed ? { ...L, caseId: next[0]!.id } : L,
    )
    onChange({ loadCases: next, loads: nextLoads })
  }
  const patchCase = (idx: number, patch: Partial<LoadCaseFormRow>) => {
    const next = model.loadCases.map((c, i) => (i === idx ? { ...c, ...patch } : c))
    setCases(next)
  }

  const addLoad = () => {
    const cid = model.loadCases[0]?.id ?? 'LC1'
    setLoads([
      ...model.loads,
      { id: uid('N'), caseId: cid, rule: 'max_z_single_node', fx: 0, fy: 0, fz: 0 },
    ])
  }
  const removeLoad = (idx: number) => {
    setLoads(model.loads.filter((_, i) => i !== idx))
  }
  const patchLoad = (idx: number, patch: Partial<NodalLoadFormRow>) => {
    setLoads(model.loads.map((L, i) => (i === idx ? { ...L, ...patch } : L)))
  }

  return (
    <div className="analysis-spec-form">
      <p className="analysis-spec-form__note">
        지지는 최소 Z 전고정(솔리드 1–3자유도) 고정입니다. 노드 명시·면압·중력 등은 백엔드 미구현입니다.
      </p>

      <div className="analysis-spec-form__block">
        <div className="analysis-spec-form__head">
          <strong>하중 케이스</strong>
          <button type="button" className="analysis-spec-form__btn" onClick={addCase}>
            + 케이스
          </button>
        </div>
        <table className="analysis-spec-form__table">
          <thead>
            <tr>
              <th>id</th>
              <th>이름</th>
              <th>category</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {model.loadCases.map((c, idx) => (
              <tr key={`${c.id}-${idx}`}>
                <td>
                  <input
                    value={c.id}
                    onChange={(e) => patchCase(idx, { id: e.target.value })}
                    aria-label={`케이스 id ${idx + 1}`}
                  />
                </td>
                <td>
                  <input
                    value={c.name}
                    onChange={(e) => patchCase(idx, { name: e.target.value })}
                    aria-label={`케이스 이름 ${idx + 1}`}
                  />
                </td>
                <td>
                  <input
                    value={c.category}
                    onChange={(e) => patchCase(idx, { category: e.target.value })}
                    aria-label={`케이스 category ${idx + 1}`}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="analysis-spec-form__btn analysis-spec-form__btn--danger"
                    disabled={model.loadCases.length <= 1}
                    onClick={() => removeCase(idx)}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="analysis-spec-form__block">
        <div className="analysis-spec-form__head">
          <strong>노드력 (nodal_force)</strong>
          <button type="button" className="analysis-spec-form__btn" onClick={addLoad}>
            + 하중 행
          </button>
        </div>
        <table className="analysis-spec-form__table">
          <thead>
            <tr>
              <th>id</th>
              <th>케이스</th>
              <th>규칙</th>
              <th>Fx [N]</th>
              <th>Fy [N]</th>
              <th>Fz [N]</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {model.loads.map((L, idx) => (
              <tr key={`${L.id}-${idx}`}>
                <td>
                  <input
                    value={L.id}
                    onChange={(e) => patchLoad(idx, { id: e.target.value })}
                    aria-label={`하중 id ${idx + 1}`}
                  />
                </td>
                <td>
                  <select
                    value={L.caseId}
                    onChange={(e) => patchLoad(idx, { caseId: e.target.value })}
                    aria-label={`하중 케이스 ${idx + 1}`}
                  >
                    {model.loadCases.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.id}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    value={L.rule}
                    onChange={(e) => patchLoad(idx, { rule: e.target.value as NodalRule })}
                    aria-label={`노드 규칙 ${idx + 1}`}
                  >
                    <option value="max_z_single_node">max_z 한 노드</option>
                    <option value="min_z_single_node">min_z 한 노드</option>
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    step={100}
                    value={Number.isFinite(L.fx) ? L.fx : 0}
                    onChange={(e) => patchLoad(idx, { fx: Number(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step={100}
                    value={Number.isFinite(L.fy) ? L.fy : 0}
                    onChange={(e) => patchLoad(idx, { fy: Number(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step={100}
                    value={Number.isFinite(L.fz) ? L.fz : 0}
                    onChange={(e) => patchLoad(idx, { fz: Number(e.target.value) })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="analysis-spec-form__btn analysis-spec-form__btn--danger"
                    disabled={model.loads.length <= 1}
                    onClick={() => removeLoad(idx)}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
