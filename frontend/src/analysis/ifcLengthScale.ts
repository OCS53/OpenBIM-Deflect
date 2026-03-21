/**
 * IFC STEP 물리 파일 앞부분에서 IFCSIUNIT(LENGTHUNIT) 를 찾아 **1 IFC 단위 = ? m** 배율을 추정합니다.
 * - IfcOpenShell(파이프라인)·Gmsh·INP·fe_results 는 일반적으로 **m** 좌표입니다.
 * - web-ifc 는 파일 단위(mm 등)를 그대로 두는 경우가 많아, 뷰어에서만 m 로 맞춥니다.
 */
const SCAN_BYTES = 900_000

export function inferIfcLengthScaleToMeters(ifcBuffer: ArrayBuffer): number {
  const n = Math.min(ifcBuffer.byteLength, SCAN_BYTES)
  const head = new TextDecoder('utf-8', { fatal: false }).decode(ifcBuffer.slice(0, n))

  const re = /#\d+=IFCSIUNIT\([^;]*?\);/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(head)) !== null) {
    const block = m[0]
    if (!/LENGTHUNIT/i.test(block)) continue
    if (/\.MILLI\./i.test(block)) return 0.001
    if (/\.CENTI\./i.test(block)) return 0.01
    if (/\.DECI\./i.test(block)) return 0.1
    if (/\.MICRO\./i.test(block)) return 1e-6
    if (/\.KILO\./i.test(block)) return 1000
    if (/\.METRE\./i.test(block)) return 1
  }
  return 1
}
