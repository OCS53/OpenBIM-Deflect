"""CalculiX ASCII `.frd` 에서 노드 변위(DISP)·응력(STRESS) 블록을 읽어 API용 `fe_results.json` 을 만듭니다."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

# 응답 JSON 크기 상한 (노드 수). 초과 시 균등 간격으로 다운샘플.
_DEFAULT_MAX = 2500


def _max_nodes() -> int:
    try:
        return max(100, int(os.environ.get("FE_RESULTS_MAX_NODES", str(_DEFAULT_MAX))))
    except ValueError:
        return _DEFAULT_MAX


def _take_sci_floats(s: str, n: int) -> list[float]:
    out: list[float] = []
    pos = 0
    while len(out) < n and pos < len(s):
        m = re.match(r"\s*([-+]?\d+\.\d+[Ee][-+]?\d+)", s[pos:])
        if not m:
            break
        out.append(float(m.group(1)))
        pos += m.start(0) + len(m.group(0))
    return out


def _parse_minus1_node_line(line: str) -> tuple[int, str] | None:
    s = line.strip()
    if not s.startswith("-1"):
        return None
    rest = s[2:].lstrip()
    j = 0
    while j < len(rest) and rest[j].isdigit():
        j += 1
    if j == 0:
        return None
    return int(rest[:j]), rest[j:].lstrip()


def _von_mises(sxx: float, syy: float, szz: float, sxy: float, syz: float, szx: float) -> float:
    return math.sqrt(
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy**2 + syz**2 + szx**2)
    )


def _find_all_block_slices(lines: list[str], keyword: str) -> list[tuple[int, int]]:
    """`-4  KEYWORD` 부터 다음 단독 `-3` 줄까지(포함) 인덱스 구간. FRD 내 순서 = *STEP 순서."""
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("-4") and keyword in lines[i]:
            start = i
            i += 1
            while i < n:
                if lines[i].strip() == "-3":
                    ranges.append((start, i))
                    i += 1
                    break
                i += 1
            continue
        i += 1
    return ranges


def _find_last_block_slice(lines: list[str], keyword: str) -> tuple[int, int] | None:
    all_r = _find_all_block_slices(lines, keyword)
    return all_r[-1] if all_r else None


def _parse_disp_lines(block_lines: list[str]) -> dict[int, tuple[float, float, float]]:
    out: dict[int, tuple[float, float, float]] = {}
    for line in block_lines:
        parsed = _parse_minus1_node_line(line)
        if not parsed:
            continue
        nid, rest = parsed
        vals = _take_sci_floats(rest, 3)
        if len(vals) == 3:
            out[nid] = (vals[0], vals[1], vals[2])
    return out


def _parse_stress_lines(block_lines: list[str]) -> dict[int, tuple[float, float, float, float, float, float]]:
    out: dict[int, tuple[float, float, float, float, float, float]] = {}
    for line in block_lines:
        parsed = _parse_minus1_node_line(line)
        if not parsed:
            continue
        nid, rest = parsed
        vals = _take_sci_floats(rest, 6)
        if len(vals) == 6:
            out[nid] = (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
    return out


def _downsample_indices(n: int, max_n: int) -> list[int]:
    if n <= max_n:
        return list(range(n))
    step = (n - 1) / (max_n - 1)
    idxs = sorted({min(n - 1, int(round(i * step))) for i in range(max_n)})
    return idxs


def _pack_disp_stress_sample(
    disp_d: dict[int, tuple[float, float, float]],
    stress_d: dict[int, tuple[float, float, float, float, float, float]],
    max_n: int,
) -> dict[str, Any]:
    """단일 DISP/STRESS 쌍 → API용 displacement·stress·magnitude·카운트."""
    if disp_d and stress_d:
        ordered_ids = sorted(set(disp_d) & set(stress_d))
        if not ordered_ids:
            ordered_ids = sorted(set(disp_d) | set(stress_d))
    elif disp_d:
        ordered_ids = sorted(disp_d.keys())
    elif stress_d:
        ordered_ids = sorted(stress_d.keys())
    else:
        ordered_ids = []

    sample_idx = _downsample_indices(len(ordered_ids), max_n)
    sampled_ids = [ordered_ids[i] for i in sample_idx]

    disp_payload: dict[str, Any] | None = None
    if disp_d:
        ux, uy, uz = [], [], []
        for nid in sampled_ids:
            if nid in disp_d:
                dx, dy, dz = disp_d[nid]
                ux.append(dx)
                uy.append(dy)
                uz.append(dz)
            else:
                ux.append(0.0)
                uy.append(0.0)
                uz.append(0.0)
        disp_payload = {"node_id": sampled_ids, "ux": ux, "uy": uy, "uz": uz}

    stress_payload: dict[str, Any] | None = None
    if stress_d:
        sxx, syy, szz, sxy, syz, szx, vm = [], [], [], [], [], [], []
        stress_ids: list[int] = []
        for nid in sampled_ids:
            if nid not in stress_d:
                continue
            t = stress_d[nid]
            stress_ids.append(nid)
            sxx.append(t[0])
            syy.append(t[1])
            szz.append(t[2])
            sxy.append(t[3])
            syz.append(t[4])
            szx.append(t[5])
            vm.append(_von_mises(*t))
        if stress_ids:
            stress_payload = {
                "node_id": stress_ids,
                "sxx": sxx,
                "syy": syy,
                "szz": szz,
                "sxy": sxy,
                "syz": syz,
                "szx": szx,
                "von_mises": vm,
            }

    max_abs_u = None
    if disp_d:
        mags = [math.sqrt(dx * dx + dy * dy + dz * dz) for dx, dy, dz in disp_d.values()]
        max_abs_u = max(mags) if mags else None

    max_vm = None
    if stress_d:
        max_vm = max(_von_mises(*t) for t in stress_d.values())

    downsample_note = None
    if len(ordered_ids) > max_n:
        downsample_note = f"노드 {len(ordered_ids)}개 중 {max_n}개만 균등 샘플링했습니다."

    return {
        "displacement": disp_payload,
        "stress": stress_payload,
        "magnitude": {
            "max_abs_displacement": max_abs_u,
            "max_von_mises": max_vm,
        },
        "n_nodes_total_disp": len(disp_d),
        "n_nodes_total_stress": len(stress_d),
        "n_nodes_in_sample": len(sampled_ids),
        "downsample_note": downsample_note,
    }


def extract_frd_summary(
    frd_path: Path,
    *,
    max_nodes: int | None = None,
    step_labels: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """
    FRD 를 읽어 컬럼형 필드 + 대표값을 담은 dict 반환.
    다중 *STEP 이면 DISP/STRESS 블록을 순서대로 읽어 `load_steps` 에 넣고,
    루트 `displacement`/`stress`/`magnitude` 는 **마지막 스텝** (기본 시각화·하위 호환).
    """
    max_n = max_nodes if max_nodes is not None else _max_nodes()
    if not frd_path.is_file():
        return {
            "version": 1,
            "source": "calculix_frd",
            "frd_basename": frd_path.name,
            "parse_error": "frd 파일 없음",
            "displacement": None,
            "stress": None,
            "magnitude": None,
        }

    text = frd_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    disp_ranges = _find_all_block_slices(lines, "DISP")
    stress_ranges = _find_all_block_slices(lines, "STRESS")

    if not disp_ranges and not stress_ranges:
        return {
            "version": 1,
            "source": "calculix_frd",
            "frd_basename": frd_path.name,
            "parse_error": "DISP/STRESS 노드 데이터를 찾지 못했습니다. *NODE FILE U 및 *EL FILE S 가 있는지 확인하세요.",
            "displacement": None,
            "stress": None,
            "magnitude": None,
        }

    n_steps = max(len(disp_ranges), len(stress_ranges), 1)
    multi = max(len(disp_ranges), len(stress_ranges)) > 1

    if not multi:
        disp_d: dict[int, tuple[float, float, float]] = {}
        stress_d: dict[int, tuple[float, float, float, float, float, float]] = {}
        if disp_ranges:
            a, b = disp_ranges[-1]
            disp_d = _parse_disp_lines(lines[a : b + 1])
        if stress_ranges:
            a, b = stress_ranges[-1]
            stress_d = _parse_stress_lines(lines[a : b + 1])
        if not disp_d and not stress_d:
            return {
                "version": 1,
                "source": "calculix_frd",
                "frd_basename": frd_path.name,
                "parse_error": "DISP/STRESS 노드 데이터를 찾지 못했습니다. *NODE FILE U 및 *EL FILE S 가 있는지 확인하세요.",
                "displacement": None,
                "stress": None,
                "magnitude": None,
            }
        packed = _pack_disp_stress_sample(disp_d, stress_d, max_n)
        return {
            "version": 1,
            "source": "calculix_frd",
            "frd_basename": frd_path.name,
            "parse_error": None,
            **packed,
        }

    load_steps: list[dict[str, Any]] = []
    for si in range(n_steps):
        disp_d = {}
        if si < len(disp_ranges):
            a, b = disp_ranges[si]
            disp_d = _parse_disp_lines(lines[a : b + 1])
        stress_d = {}
        if si < len(stress_ranges):
            a, b = stress_ranges[si]
            stress_d = _parse_stress_lines(lines[a : b + 1])
        packed = _pack_disp_stress_sample(disp_d, stress_d, max_n)
        cid = step_labels[si][0] if step_labels and si < len(step_labels) else ""
        nm = step_labels[si][1] if step_labels and si < len(step_labels) else ""
        load_steps.append(
            {
                "step_index": si + 1,
                "case_id": cid,
                "name": nm,
                **packed,
            }
        )

    if not load_steps:
        return {
            "version": 1,
            "source": "calculix_frd",
            "frd_basename": frd_path.name,
            "parse_error": "다중 STEP FRD 파싱 결과가 비었습니다.",
            "displacement": None,
            "stress": None,
            "magnitude": None,
        }

    primary = load_steps[-1]
    return {
        "version": 1,
        "source": "calculix_frd",
        "frd_basename": frd_path.name,
        "parse_error": None,
        "n_steps_in_frd": len(load_steps),
        "n_nodes_total_disp": primary["n_nodes_total_disp"],
        "n_nodes_total_stress": primary["n_nodes_total_stress"],
        "n_nodes_in_sample": primary["n_nodes_in_sample"],
        "downsample_note": primary.get("downsample_note"),
        "displacement": primary["displacement"],
        "stress": primary["stress"],
        "magnitude": primary["magnitude"],
        "load_steps": load_steps,
    }


def _attach_xyz_to_displacement_block(disp: dict[str, Any], inp_path: Path) -> None:
    """샘플된 displacement 블록에 INP *NODE 좌표(x,y,z) 부착."""
    from app.services.ccx_inp_nodes import parse_ccx_inp_nodes

    if not disp or not isinstance(disp, dict):
        return
    nids = disp.get("node_id")
    if not isinstance(nids, list) or not nids:
        return
    coords = parse_ccx_inp_nodes(inp_path)
    if not coords:
        return
    xs, ys, zs = [], [], []
    for nid in nids:
        t = coords.get(int(nid))
        if t:
            xs.append(t[0])
            ys.append(t[1])
            zs.append(t[2])
        else:
            xs.append(float("nan"))
            ys.append(float("nan"))
            zs.append(float("nan"))
    if any(not math.isnan(x) for x in xs):
        disp["x"] = xs
        disp["y"] = ys
        disp["z"] = zs


def _attach_reference_positions(
    summary: dict[str, Any],
    inp_path: Path,
) -> None:
    """루트 및 load_steps[] 의 displacement 에 참조 좌표 부착."""
    root = summary.get("displacement")
    if isinstance(root, dict):
        _attach_xyz_to_displacement_block(root, inp_path)
    for step in summary.get("load_steps") or []:
        if isinstance(step, dict):
            d = step.get("displacement")
            if isinstance(d, dict):
                _attach_xyz_to_displacement_block(d, inp_path)


def write_fe_results_json(
    out_dir: Path,
    frd_basename: str = "model_from_pipeline.frd",
    inp_basename: str = "model_from_pipeline.inp",
) -> dict[str, Any]:
    frd = out_dir / frd_basename
    step_labels: list[tuple[str, str]] | None = None
    ain = out_dir / "analysis_input.json"
    if ain.is_file():
        try:
            from app.analysis.load_spec_v1 import AnalysisInputV1
            from app.analysis.resolve_static_v1 import load_case_step_order_from_spec

            spec = AnalysisInputV1.model_validate(json.loads(ain.read_text(encoding="utf-8")))
            step_labels = load_case_step_order_from_spec(spec)
        except Exception:
            step_labels = None
    summary = extract_frd_summary(frd, step_labels=step_labels)
    inp = out_dir / inp_basename
    if inp.is_file():
        _attach_reference_positions(summary, inp)
    out_path = out_dir / "fe_results.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def read_fe_results_json(out_dir: Path) -> dict[str, Any] | None:
    p = out_dir / "fe_results.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_fe_results_payload(out_dir: Path):
    from app.schemas import FeResultsPayload

    raw = read_fe_results_json(out_dir)
    if not raw:
        return None
    try:
        return FeResultsPayload.model_validate(raw)
    except Exception:
        return None
