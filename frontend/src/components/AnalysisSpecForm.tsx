/**
 * AnalysisInputV1 폼 — nodal_force + surface_pressure(exterior) + gravity + min_z 지지.
 * @see docs/LOAD-MODEL-AND-INP.md
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { parseExplicitNodeIds, sanitizeExplicitNodeIdsText } from '../analysis/explicitNodeIdsInput'
import './AnalysisSpecForm.css'

const MESH_DATALIST_CAP = 400
const MESH_MULTISELECT_MAX = 2000

export type NodalRule = 'max_z_single_node' | 'min_z_single_node'

export type NodalTargetFormMode = 'rule' | 'explicit'

export type LoadFormKind = 'nodal_force' | 'surface_pressure' | 'gravity'

export interface LoadCaseFormRow {
  id: string
  name: string
  category: string
}

export interface NodalLoadFormRow {
  kind: 'nodal_force'
  id: string
  caseId: string
  targetMode: NodalTargetFormMode
  rule: NodalRule
  /** targetMode === 'explicit' 일 때 쉼표·공백 구분 메시 노드 태그 */
  explicitNodeIdsText: string
  fx: number
  fy: number
  fz: number
}

export interface SurfacePressureLoadFormRow {
  kind: 'surface_pressure'
  id: string
  caseId: string
  /** Pa */
  magnitude: number
  /** null 이면 JSON 에 생략(전체 외곽면) */
  normalMaxTiltDeg: number | null
}

export interface GravityLoadFormRow {
  kind: 'gravity'
  id: string
  caseId: string
  /** m/s² */
  ax: number
  ay: number
  az: number
}

export type LoadFormRow = NodalLoadFormRow | SurfacePressureLoadFormRow | GravityLoadFormRow

/** 하중 조합 한 행 — `factorsByCaseIndex[i]` 는 `loadCases[i]` 에 대한 계수(문자열 입력) */
export interface LoadCombinationFormRow {
  id: string
  name: string
  factorsByCaseIndex: string[]
}

export interface AnalysisSpecFormModel {
  loadCases: LoadCaseFormRow[]
  loads: LoadFormRow[]
  combinations: LoadCombinationFormRow[]
  /**
   * 중력 하중이 있을 때 JSON `material_density_kg_m3` 로 넣음. 비우면 생략 → API `density_kg_m3` 쿼리 사용.
   */
  materialDensityKgM3Text: string
}

export function defaultAnalysisSpecFormModel(): AnalysisSpecFormModel {
  return {
    loadCases: [{ id: 'LC1', name: '', category: 'GENERAL' }],
    combinations: [],
    materialDensityKgM3Text: '',
    loads: [
      {
        kind: 'nodal_force',
        id: 'N1',
        caseId: 'LC1',
        targetMode: 'rule',
        rule: 'max_z_single_node',
        explicitNodeIdsText: '',
        fx: 0,
        fy: 0,
        fz: -10_000,
      },
    ],
  }
}

function loadRowToApiJson(L: LoadFormRow, caseIdTrim: string): Record<string, unknown> | null {
  const idTrim =
    L.id.trim() ||
    (L.kind === 'nodal_force' ? `N_${caseIdTrim}` : L.kind === 'surface_pressure' ? `P_${caseIdTrim}` : `G_${caseIdTrim}`)
  if (L.kind === 'nodal_force') {
    if (L.targetMode === 'rule') {
      return {
        type: 'nodal_force',
        id: idTrim,
        case_id: caseIdTrim,
        target: { mode: 'rule', rule: L.rule },
        components: [L.fx, L.fy, L.fz],
      }
    }
    const nodeIds = parseExplicitNodeIds(L.explicitNodeIdsText)
    if (nodeIds == null) return null
    return {
      type: 'nodal_force',
      id: idTrim,
      case_id: caseIdTrim,
      target: { mode: 'explicit', node_ids: nodeIds },
      components: [L.fx, L.fy, L.fz],
    }
  }
  if (L.kind === 'gravity') {
    const ax = L.ax
    const ay = L.ay
    const az = L.az
    if (!Number.isFinite(ax) || !Number.isFinite(ay) || !Number.isFinite(az)) return null
    if (ax === 0 && ay === 0 && az === 0) return null
    return {
      type: 'gravity',
      id: idTrim,
      case_id: caseIdTrim,
      acceleration: [ax, ay, az],
    }
  }
  if (!Number.isFinite(L.magnitude)) return null
  const sel: Record<string, unknown> = { kind: 'exterior' }
  if (L.normalMaxTiltDeg != null) {
    const t = L.normalMaxTiltDeg
    if (!Number.isFinite(t) || t < 0 || t > 90) return null
    sel.normal_max_tilt_deg = t
  }
  return {
    type: 'surface_pressure',
    id: idTrim,
    case_id: caseIdTrim,
    magnitude: L.magnitude,
    selection: sel,
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
  const loadsJson: Record<string, unknown>[] = []
  for (const L of model.loads) {
    const j = loadRowToApiJson(L, L.caseId.trim())
    if (j == null) return null
    loadsJson.push(j)
  }
  const loadCasesJson = model.loadCases.map((c) => ({
    id: c.id.trim(),
    name: c.name.trim(),
    category: c.category.trim() || 'GENERAL',
  }))
  const lcIdSet = new Set(loadCasesJson.map((c) => c.id))

  const combinationsJson: Record<string, unknown>[] = []
  const combIdSeen = new Set<string>()
  for (const row of model.combinations) {
    const cid = row.id.trim()
    if (!cid) return null
    if (lcIdSet.has(cid)) return null
    if (combIdSeen.has(cid)) return null
    combIdSeen.add(cid)

    const fac: Record<string, number> = {}
    const n = Math.min(row.factorsByCaseIndex.length, model.loadCases.length)
    for (let i = 0; i < n; i++) {
      const t = (row.factorsByCaseIndex[i] ?? '').trim()
      if (t === '') continue
      const v = Number(t.replace(',', '.'))
      if (!Number.isFinite(v)) return null
      const caseId = model.loadCases[i]!.id.trim()
      if (!caseId) return null
      fac[caseId] = v
    }
    if (Object.keys(fac).length < 1) return null
    combinationsJson.push({
      id: cid,
      name: row.name.trim(),
      factors: fac,
    })
  }

  const out: Record<string, unknown> = {
    version: 1,
    analysis_type: 'static_linear',
    load_cases: loadCasesJson,
    supports: [
      {
        id: 'fix_min_z',
        selection: { type: 'min_z' },
        fixed_dofs: [1, 2, 3],
      },
    ],
    loads: loadsJson,
  }
  if (combinationsJson.length > 0) out.combinations = combinationsJson

  const densT = model.materialDensityKgM3Text.trim()
  if (densT !== '') {
    const rho = Number(densT.replace(',', '.'))
    if (!Number.isFinite(rho) || rho <= 0) return null
    out.material_density_kg_m3 = rho
  }

  return out
}

function uid(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`
}

interface AnalysisSpecFormProps {
  model: AnalysisSpecFormModel
  onChange: (m: AnalysisSpecFormModel) => void
  /**
   * 마지막 파이프라인 fe_results 변위 블록의 node_id (다운샘플·스텝에 따름).
   * 없으면 메시 자동완성·다중 선택 숨김.
   */
  meshNodeIdSample?: readonly number[] | null
}

function defaultNodalRow(caseId: string): NodalLoadFormRow {
  return {
    kind: 'nodal_force',
    id: uid('N'),
    caseId,
    targetMode: 'rule',
    rule: 'max_z_single_node',
    explicitNodeIdsText: '',
    fx: 0,
    fy: 0,
    fz: 0,
  }
}

function defaultSurfaceRow(caseId: string): SurfacePressureLoadFormRow {
  return {
    kind: 'surface_pressure',
    id: uid('P'),
    caseId,
    magnitude: 1000,
    normalMaxTiltDeg: null,
  }
}

function defaultGravityRow(caseId: string): GravityLoadFormRow {
  return {
    kind: 'gravity',
    id: uid('G'),
    caseId,
    ax: 0,
    ay: 0,
    az: -9.81,
  }
}

export function AnalysisSpecForm({ model, onChange, meshNodeIdSample }: AnalysisSpecFormProps) {
  const setCases = (loadCases: LoadCaseFormRow[]) => onChange({ ...model, loadCases })
  const setLoads = (loads: LoadFormRow[]) => onChange({ ...model, loads })
  const setCombinations = (combinations: LoadCombinationFormRow[]) =>
    onChange({ ...model, combinations })

  const meshIdsSorted = useMemo(() => {
    if (!meshNodeIdSample?.length) return []
    const u = [...new Set(meshNodeIdSample)].filter((n) => Number.isFinite(n) && n > 0)
    u.sort((a, b) => a - b)
    return u.slice(0, MESH_MULTISELECT_MAX)
  }, [meshNodeIdSample])

  const meshIdsForDatalist = useMemo(
    () => meshIdsSorted.slice(0, MESH_DATALIST_CAP),
    [meshIdsSorted],
  )

  const defaultCase = model.loadCases[0]?.id ?? 'LC1'
  const [bulkText, setBulkText] = useState('')
  const [bulkCaseId, setBulkCaseId] = useState(defaultCase)
  const [bulkFx, setBulkFx] = useState(0)
  const [bulkFy, setBulkFy] = useState(0)
  const [bulkFz, setBulkFz] = useState(-10_000)
  const meshMultiRef = useRef<HTMLSelectElement>(null)

  useEffect(() => {
    const ids = model.loadCases.map((c) => c.id)
    if (!ids.includes(bulkCaseId)) setBulkCaseId(ids[0] ?? 'LC1')
  }, [model.loadCases, bulkCaseId])

  const mergeExplicitNodeIds = (baseText: string, extra: number[]): string => {
    const cur = parseExplicitNodeIds(baseText) ?? []
    const seen = new Set(cur)
    for (const id of extra) {
      if (seen.has(id)) continue
      seen.add(id)
      cur.push(id)
    }
    return cur.join(', ')
  }

  const appendSelectedMeshToExplicit = () => {
    const el = meshMultiRef.current
    if (!el) return
    const picked = Array.from(el.selectedOptions)
      .map((o) => Number(o.value))
      .filter((n) => n > 0)
    if (picked.length === 0) return

    const idx = model.loads.findIndex(
      (L) => L.kind === 'nodal_force' && L.targetMode === 'explicit',
    )
    if (idx >= 0) {
      setLoads(
        model.loads.map((L, i) => {
          if (i !== idx || L.kind !== 'nodal_force') return L
          const nl = L as NodalLoadFormRow
          return {
            ...nl,
            explicitNodeIdsText: mergeExplicitNodeIds(nl.explicitNodeIdsText, picked),
          }
        }),
      )
      return
    }
    setLoads([
      ...model.loads,
      {
        kind: 'nodal_force',
        id: uid('N'),
        caseId: model.loadCases[0]?.id ?? 'LC1',
        targetMode: 'explicit',
        rule: 'max_z_single_node',
        explicitNodeIdsText: picked.join(', '),
        fx: 0,
        fy: 0,
        fz: -10_000,
      },
    ])
  }

  const appendBulkNodalRows = () => {
    const lines = bulkText
      .split(/\r?\n/)
      .map((ln) => sanitizeExplicitNodeIdsText(ln))
      .map((ln) => ln.trim())
      .filter(Boolean)
    const cid = bulkCaseId.trim()
    if (!model.loadCases.some((c) => c.id === cid)) return

    const newRows: NodalLoadFormRow[] = []
    for (const line of lines) {
      const ids = parseExplicitNodeIds(line)
      if (!ids) continue
      newRows.push({
        kind: 'nodal_force',
        id: uid('N'),
        caseId: cid,
        targetMode: 'explicit',
        rule: 'max_z_single_node',
        explicitNodeIdsText: ids.join(', '),
        fx: bulkFx,
        fy: bulkFy,
        fz: bulkFz,
      })
    }
    if (newRows.length === 0) return
    setLoads([...model.loads, ...newRows])
  }

  const addCase = () => {
    const n = model.loadCases.length + 1
    onChange({
      ...model,
      loadCases: [...model.loadCases, { id: `LC${n}`, name: '', category: 'GENERAL' }],
      combinations: model.combinations.map((c) => ({
        ...c,
        factorsByCaseIndex: [...c.factorsByCaseIndex, ''],
      })),
    })
  }
  const removeCase = (idx: number) => {
    const removed = model.loadCases[idx]?.id
    const next = model.loadCases.filter((_, i) => i !== idx)
    if (next.length === 0) return
    const nextLoads = model.loads.map((L) =>
      L.caseId === removed ? { ...L, caseId: next[0]!.id } : L,
    )
    onChange({
      ...model,
      loadCases: next,
      loads: nextLoads,
      combinations: model.combinations.map((c) => ({
        ...c,
        factorsByCaseIndex: c.factorsByCaseIndex.filter((_, i) => i !== idx),
      })),
    })
  }
  const patchCase = (idx: number, patch: Partial<LoadCaseFormRow>) => {
    const next = model.loadCases.map((c, i) => (i === idx ? { ...c, ...patch } : c))
    setCases(next)
  }

  const addNodalLoad = () => {
    const cid = model.loadCases[0]?.id ?? 'LC1'
    setLoads([...model.loads, defaultNodalRow(cid)])
  }
  const addSurfaceLoad = () => {
    const cid = model.loadCases[0]?.id ?? 'LC1'
    setLoads([...model.loads, defaultSurfaceRow(cid)])
  }
  const addGravityLoad = () => {
    const cid = model.loadCases[0]?.id ?? 'LC1'
    setLoads([...model.loads, defaultGravityRow(cid)])
  }
  const removeLoad = (idx: number) => {
    setLoads(model.loads.filter((_, i) => i !== idx))
  }
  const patchNodal = (idx: number, patch: Partial<Omit<NodalLoadFormRow, 'kind'>>) => {
    setLoads(
      model.loads.map((L, i) => (i === idx && L.kind === 'nodal_force' ? { ...L, ...patch } : L)),
    )
  }
  const patchSurface = (idx: number, patch: Partial<Omit<SurfacePressureLoadFormRow, 'kind'>>) => {
    setLoads(
      model.loads.map((L, i) =>
        i === idx && L.kind === 'surface_pressure' ? { ...L, ...patch } : L,
      ),
    )
  }
  const patchGravity = (idx: number, patch: Partial<Omit<GravityLoadFormRow, 'kind'>>) => {
    setLoads(
      model.loads.map((L, i) => (i === idx && L.kind === 'gravity' ? { ...L, ...patch } : L)),
    )
  }
  const setLoadKind = (idx: number, kind: LoadFormKind) => {
    const L = model.loads[idx]
    if (!L) return
    const cid = L.caseId
    const row: LoadFormRow =
      kind === 'nodal_force'
        ? defaultNodalRow(cid)
        : kind === 'surface_pressure'
          ? defaultSurfaceRow(cid)
          : defaultGravityRow(cid)
    row.id = L.id
    row.caseId = cid
    setLoads(model.loads.map((x, i) => (i === idx ? row : x)))
  }

  const addCombination = () => {
    const factorsByCaseIndex = model.loadCases.map(() => '')
    if (factorsByCaseIndex.length > 0) factorsByCaseIndex[0] = '1'
    setCombinations([
      ...model.combinations,
      { id: uid('COMB'), name: '', factorsByCaseIndex },
    ])
  }
  const removeCombination = (idx: number) => {
    setCombinations(model.combinations.filter((_, i) => i !== idx))
  }
  const patchCombination = (idx: number, patch: Partial<Omit<LoadCombinationFormRow, 'factorsByCaseIndex'>>) => {
    setCombinations(
      model.combinations.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    )
  }
  const patchCombinationFactor = (combIdx: number, caseIdx: number, text: string) => {
    setCombinations(
      model.combinations.map((c, i) => {
        if (i !== combIdx) return c
        const next = [...c.factorsByCaseIndex]
        while (next.length < model.loadCases.length) next.push('')
        next[caseIdx] = text
        return { ...c, factorsByCaseIndex: next }
      }),
    )
  }

  const meshDatalistId = 'analysis-spec-mesh-node-datalist'

  return (
    <div className="analysis-spec-form">
      {meshIdsForDatalist.length > 0 ? (
        <datalist id={meshDatalistId}>
          {meshIdsForDatalist.map((id) => (
            <option key={id} value={String(id)} />
          ))}
        </datalist>
      ) : null}
      <p className="analysis-spec-form__note">
        지지는 최소 Z 전고정(솔리드 1–3자유도)입니다. 면압·중력은 C3D4 등가 절점하중으로 해석됩니다. 조합 id 는 하중
        케이스 id 와 겹치면 안 됩니다.
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
          <strong>하중 조합</strong>
          <button type="button" className="analysis-spec-form__btn" onClick={addCombination}>
            + 조합
          </button>
        </div>
        <p className="analysis-spec-form__note analysis-spec-form__note--tight">
          각 열은 위 케이스 순서와 같습니다. 비워 둔 케이스는 조합에 포함되지 않습니다. 한 조합에 최소 하나의 계수가
          있어야 전송됩니다.
        </p>
        {model.combinations.length === 0 ? (
          <p className="analysis-spec-form__empty-comb">조합이 없으면 케이스별 STEP 만 생성됩니다.</p>
        ) : (
          <div className="analysis-spec-form__comb-scroll">
            <table className="analysis-spec-form__table analysis-spec-form__table--comb">
              <thead>
                <tr>
                  <th>id</th>
                  <th>이름</th>
                  {model.loadCases.map((c, ci) => (
                    <th key={`${c.id}-${ci}-h`} title={`케이스 ${c.id} 계수`}>
                      γ·{c.id || `(${ci + 1})`}
                    </th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {model.combinations.map((row, ri) => (
                  <tr key={`comb-${row.id}-${ri}`}>
                    <td>
                      <input
                        value={row.id}
                        onChange={(e) => patchCombination(ri, { id: e.target.value })}
                        aria-label={`조합 id ${ri + 1}`}
                      />
                    </td>
                    <td>
                      <input
                        value={row.name}
                        onChange={(e) => patchCombination(ri, { name: e.target.value })}
                        aria-label={`조합 이름 ${ri + 1}`}
                      />
                    </td>
                    {model.loadCases.map((_, ci) => (
                      <td key={`f-${ri}-${ci}`}>
                        <input
                          className="analysis-spec-form__factor-input"
                          type="text"
                          inputMode="decimal"
                          autoComplete="off"
                          placeholder="—"
                          value={row.factorsByCaseIndex[ci] ?? ''}
                          onChange={(e) => patchCombinationFactor(ri, ci, e.target.value)}
                          aria-label={`조합 ${ri + 1} 케이스 ${ci + 1} 계수`}
                        />
                      </td>
                    ))}
                    <td>
                      <button
                        type="button"
                        className="analysis-spec-form__btn analysis-spec-form__btn--danger"
                        onClick={() => removeCombination(ri)}
                      >
                        삭제
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="analysis-spec-form__block">
        <div className="analysis-spec-form__head">
          <strong>하중 (노드력 · 외곽 면압 · 중력)</strong>
          <span className="analysis-spec-form__btn-group">
            <button type="button" className="analysis-spec-form__btn" onClick={addNodalLoad}>
              + 노드력
            </button>
            <button type="button" className="analysis-spec-form__btn" onClick={addSurfaceLoad}>
              + 외곽 면압
            </button>
            <button type="button" className="analysis-spec-form__btn" onClick={addGravityLoad}>
              + 중력
            </button>
          </span>
        </div>
        <div className="analysis-spec-form__density-row">
          <label className="analysis-spec-form__density-label">
            material_density_kg_m3 (선택)
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              placeholder="비우면 패널 density 쿼리"
              title="중력 행이 있을 때 비우면 Analysis 패널의 density(kg/m³) 쿼리가 사용됩니다."
              value={model.materialDensityKgM3Text}
              onChange={(e) => onChange({ ...model, materialDensityKgM3Text: e.target.value })}
              aria-label="material_density_kg_m3 선택 입력"
            />
          </label>
        </div>
        <table className="analysis-spec-form__table">
          <thead>
            <tr>
              <th>id</th>
              <th>케이스</th>
              <th>유형</th>
              <th>값</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {model.loads.map((L, idx) => (
              <tr key={`${L.kind}-${L.id}-${idx}`}>
                <td>
                  <input
                    value={L.id}
                    onChange={(e) =>
                      L.kind === 'nodal_force'
                        ? patchNodal(idx, { id: e.target.value })
                        : L.kind === 'surface_pressure'
                          ? patchSurface(idx, { id: e.target.value })
                          : patchGravity(idx, { id: e.target.value })
                    }
                    aria-label={`하중 id ${idx + 1}`}
                  />
                </td>
                <td>
                  <select
                    value={L.caseId}
                    onChange={(e) =>
                      L.kind === 'nodal_force'
                        ? patchNodal(idx, { caseId: e.target.value })
                        : L.kind === 'surface_pressure'
                          ? patchSurface(idx, { caseId: e.target.value })
                          : patchGravity(idx, { caseId: e.target.value })
                    }
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
                    value={L.kind}
                    onChange={(e) => setLoadKind(idx, e.target.value as LoadFormKind)}
                    aria-label={`하중 유형 ${idx + 1}`}
                  >
                    <option value="nodal_force">노드력</option>
                    <option value="surface_pressure">외곽 면압</option>
                    <option value="gravity">중력</option>
                  </select>
                </td>
                <td>
                  {L.kind === 'nodal_force' ? (
                    <div className="analysis-spec-form__load-detail">
                      <select
                        value={L.targetMode}
                        onChange={(e) =>
                          patchNodal(idx, {
                            targetMode: e.target.value as NodalTargetFormMode,
                          })
                        }
                        aria-label={`노드력 대상 ${idx + 1}`}
                      >
                        <option value="rule">규칙 (max/min z)</option>
                        <option value="explicit">명시 노드 ID</option>
                      </select>
                      {L.targetMode === 'rule' ? (
                        <select
                          value={L.rule}
                          onChange={(e) => patchNodal(idx, { rule: e.target.value as NodalRule })}
                          aria-label={`노드 규칙 ${idx + 1}`}
                        >
                          <option value="max_z_single_node">max_z 한 노드</option>
                          <option value="min_z_single_node">min_z 한 노드</option>
                        </select>
                      ) : (
                        <input
                          className="analysis-spec-form__node-ids"
                          type="text"
                          inputMode="numeric"
                          autoComplete="off"
                          placeholder="예: 4 또는 10, 20, 30"
                          title="숫자와 쉼표·세미콜론·공백만 허용(붙여넣기 시 비숫자 문자는 제거)"
                          list={meshIdsForDatalist.length > 0 ? meshDatalistId : undefined}
                          value={L.explicitNodeIdsText}
                          onChange={(e) =>
                            patchNodal(idx, {
                              explicitNodeIdsText: sanitizeExplicitNodeIdsText(e.target.value),
                            })
                          }
                          aria-label={`명시 노드 ID ${idx + 1}`}
                        />
                      )}
                      <label className="analysis-spec-form__inline-num">
                        Fx
                        <input
                          type="number"
                          step={100}
                          value={Number.isFinite(L.fx) ? L.fx : 0}
                          onChange={(e) => patchNodal(idx, { fx: Number(e.target.value) })}
                        />
                      </label>
                      <label className="analysis-spec-form__inline-num">
                        Fy
                        <input
                          type="number"
                          step={100}
                          value={Number.isFinite(L.fy) ? L.fy : 0}
                          onChange={(e) => patchNodal(idx, { fy: Number(e.target.value) })}
                        />
                      </label>
                      <label className="analysis-spec-form__inline-num">
                        Fz
                        <input
                          type="number"
                          step={100}
                          value={Number.isFinite(L.fz) ? L.fz : 0}
                          onChange={(e) => patchNodal(idx, { fz: Number(e.target.value) })}
                        />
                      </label>
                      <span className="analysis-spec-form__unit-hint">N</span>
                    </div>
                  ) : L.kind === 'surface_pressure' ? (
                    <div className="analysis-spec-form__load-detail">
                      <label className="analysis-spec-form__inline-num">
                        p
                        <input
                          type="number"
                          step={100}
                          value={Number.isFinite(L.magnitude) ? L.magnitude : 0}
                          onChange={(e) => patchSurface(idx, { magnitude: Number(e.target.value) })}
                        />
                      </label>
                      <span className="analysis-spec-form__unit-hint">Pa</span>
                      <label
                        className="analysis-spec-form__inline-num analysis-spec-form__tilt"
                        title="법선과 +Z 사이 각 θ에 대해 |θ−90°| ≤ 입력값(°). 비우면 모든 외곽면."
                      >
                        틸트
                        <input
                          type="number"
                          min={0}
                          max={90}
                          step={1}
                          placeholder="전체"
                          value={L.normalMaxTiltDeg ?? ''}
                          onChange={(e) => {
                            const v = e.target.value
                            patchSurface(idx, {
                              normalMaxTiltDeg: v === '' ? null : Number(v),
                            })
                          }}
                          aria-label={`면압 외벽 틸트 한도 도 ${idx + 1}`}
                        />
                      </label>
                      <span className="analysis-spec-form__unit-hint">°</span>
                    </div>
                  ) : (
                    <div className="analysis-spec-form__load-detail">
                      <label className="analysis-spec-form__inline-num">
                        ax
                        <input
                          type="number"
                          step={0.01}
                          value={Number.isFinite(L.ax) ? L.ax : 0}
                          onChange={(e) => patchGravity(idx, { ax: Number(e.target.value) })}
                        />
                      </label>
                      <label className="analysis-spec-form__inline-num">
                        ay
                        <input
                          type="number"
                          step={0.01}
                          value={Number.isFinite(L.ay) ? L.ay : 0}
                          onChange={(e) => patchGravity(idx, { ay: Number(e.target.value) })}
                        />
                      </label>
                      <label className="analysis-spec-form__inline-num">
                        az
                        <input
                          type="number"
                          step={0.01}
                          value={Number.isFinite(L.az) ? L.az : 0}
                          onChange={(e) => patchGravity(idx, { az: Number(e.target.value) })}
                        />
                      </label>
                      <span className="analysis-spec-form__unit-hint">m/s²</span>
                    </div>
                  )}
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
        <details className="analysis-spec-form__details">
          <summary>명시 노드 일괄 입력 · 메시 태그</summary>
          <div className="analysis-spec-form__bulk">
            <p className="analysis-spec-form__details-note">
              한 줄에 하나의 <strong>명시 노드력</strong> 행이 됩니다(쉼표로 여러 ID). 공통 케이스·Fx,Fy,Fz 는 아래에서
              지정합니다.
            </p>
            <textarea
              className="analysis-spec-form__bulk-textarea"
              rows={5}
              spellCheck={false}
              placeholder={'4\n10, 20, 30'}
              value={bulkText}
              onChange={(e) => setBulkText(sanitizeExplicitNodeIdsText(e.target.value))}
              aria-label="명시 노드 일괄 줄 입력"
            />
            <div className="analysis-spec-form__bulk-toolbar">
              <label className="analysis-spec-form__bulk-field">
                케이스
                <select
                  value={bulkCaseId}
                  onChange={(e) => setBulkCaseId(e.target.value)}
                  aria-label="일괄 추가 케이스"
                >
                  {model.loadCases.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.id}
                    </option>
                  ))}
                </select>
              </label>
              <label className="analysis-spec-form__bulk-field">
                Fx
                <input
                  type="number"
                  step={100}
                  value={Number.isFinite(bulkFx) ? bulkFx : 0}
                  onChange={(e) => setBulkFx(Number(e.target.value))}
                />
              </label>
              <label className="analysis-spec-form__bulk-field">
                Fy
                <input
                  type="number"
                  step={100}
                  value={Number.isFinite(bulkFy) ? bulkFy : 0}
                  onChange={(e) => setBulkFy(Number(e.target.value))}
                />
              </label>
              <label className="analysis-spec-form__bulk-field">
                Fz
                <input
                  type="number"
                  step={100}
                  value={Number.isFinite(bulkFz) ? bulkFz : 0}
                  onChange={(e) => setBulkFz(Number(e.target.value))}
                />
              </label>
              <button type="button" className="analysis-spec-form__btn" onClick={appendBulkNodalRows}>
                일괄 행 추가
              </button>
            </div>
          </div>
          {meshIdsSorted.length > 0 ? (
            <div className="analysis-spec-form__mesh-pick">
              <p className="analysis-spec-form__details-note">
                마지막 FRD 변위 샘플의 노드 ID입니다(다운샘플·스텝에 따름). 자동완성은 앞{' '}
                {MESH_DATALIST_CAP}개만. Ctrl/⌘ 클릭으로 여러 개 선택 후 아래 버튼으로 명시란에 합칩니다.
              </p>
              <select
                ref={meshMultiRef}
                className="analysis-spec-form__mesh-multiselect"
                multiple
                size={8}
                aria-label="메시 노드 ID 다중 선택"
              >
                {meshIdsSorted.map((id) => (
                  <option key={id} value={String(id)}>
                    {id}
                  </option>
                ))}
              </select>
              <button type="button" className="analysis-spec-form__btn" onClick={appendSelectedMeshToExplicit}>
                선택 ID → 첫 명시 노드력에 추가
              </button>
            </div>
          ) : (
            <p className="analysis-spec-form__details-note analysis-spec-form__details-note--muted">
              파이프라인 완료 후 fe_results 변위가 있으면 여기에 메시 노드 목록이 표시됩니다.
            </p>
          )}
        </details>
      </div>
    </div>
  )
}
