"""CalculiX `.inp` 의 `*NODE` 블록에서 노드 ID → (x,y,z) 추출."""

from __future__ import annotations

from pathlib import Path


def parse_ccx_inp_nodes(inp_path: Path) -> dict[int, tuple[float, float, float]]:
    if not inp_path.is_file():
        return {}
    text = inp_path.read_text(encoding="ascii", errors="replace")
    out: dict[int, tuple[float, float, float]] = {}
    in_node = False
    for line in text.splitlines():
        ls = line.strip()
        if not ls:
            continue
        u = ls.upper()
        if u.startswith("*NODE"):
            in_node = True
            continue
        if in_node and ls.startswith("*"):
            break
        if not in_node:
            continue
        if ls.startswith("**"):
            continue
        parts = [p.strip() for p in ls.split(",")]
        if len(parts) < 4:
            continue
        try:
            nid = int(float(parts[0]))
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            out[nid] = (x, y, z)
        except ValueError:
            continue
    return out
