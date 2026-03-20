#!/usr/bin/env python3
"""
Docker 이미지 안에서 IfcOpenShell · Gmsh · CalculiX(ccx) 가동 여부를 한 번에 검사합니다.

IfcOpenShell → (중간 형상) → Gmsh → CalculiX 전체 파이프라인은 추후 노트북/스크립트로 확장하고,
여기서는 도구 체인·최소 해석 입력이 동작하는지 확인합니다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BEAM = ROOT / "sample" / "simple_beam.ifc"
CUBE_DIR = Path(__file__).resolve().parent / "fixtures" / "minimal_cube"


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=True,
    )


def check_ccx_gmsh_cli() -> None:
    ccx = shutil.which("ccx")
    gmsh = shutil.which("gmsh")
    assert ccx, "ccx (calculix-ccx) not on PATH"
    assert gmsh, "gmsh not on PATH"
    print("ccx:", ccx)
    r = _run([ccx, "-v"])
    print("ccx -v (first line):", (r.stdout or r.stderr).strip().splitlines()[:1])
    r = _run([gmsh, "--version"])
    print("gmsh --version:", (r.stdout or r.stderr).strip().splitlines()[:1])


def check_ifcopenshell_sample() -> None:
    import ifcopenshell

    if not SAMPLE_BEAM.is_file():
        print("WARN: sample IFC missing:", SAMPLE_BEAM, file=sys.stderr)
        return
    f = ifcopenshell.open(str(SAMPLE_BEAM))
    beams = f.by_type("IfcBeam")
    print("ifcopenshell:", ifcopenshell.version, "| IfcBeam count:", len(beams))


def check_gmsh_python_box_mesh() -> None:
    import gmsh

    gmsh.initialize()
    try:
        gmsh.model.add("spike_box")
        gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
        gmsh.model.occ.synchronize()
        gmsh.model.mesh.generate(3)
        out = Path("/tmp/openbim_spike_box.msh")
        gmsh.write(str(out))
        print("Gmsh 3D mesh written:", out, "size", out.stat().st_size, "bytes")
    finally:
        gmsh.finalize()


def check_calculix_minimal_cube() -> None:
    inp = CUBE_DIR / "cube.inp"
    assert inp.is_file(), f"missing {inp}"
    # CalculiX: 입력 stem이 잡 이름 (cube.inp → ccx cube). 임시 디렉터리에서 실행해 리포에 산출물이 남지 않게 함.
    with tempfile.TemporaryDirectory(prefix="openbim_ccx_") as td:
        tdir = Path(td)
        shutil.copy(inp, tdir / "cube.inp")
        r = _run(["ccx", "cube"], cwd=tdir)
        if r.returncode != 0:
            print("ccx stderr:", r.stderr[:2000], file=sys.stderr)
            raise SystemExit(f"ccx failed with code {r.returncode}")
        frd = tdir / "cube.frd"
        dat = tdir / "cube.dat"
        if frd.is_file():
            print("CalculiX output:", frd.name, frd.stat().st_size, "bytes (tmp)")
        elif dat.is_file():
            print("CalculiX output:", dat.name, dat.stat().st_size, "bytes (tmp)")
        else:
            print("WARN: neither cube.frd nor cube.dat found after ccx", file=sys.stderr)


def main() -> None:
    print("ROOT (mounted workdir):", ROOT)
    check_ccx_gmsh_cli()
    check_ifcopenshell_sample()
    check_gmsh_python_box_mesh()
    check_calculix_minimal_cube()
    print("toolcheck: OK")


if __name__ == "__main__":
    main()
