/**
 * 명시 노드 ID 입력 — 숫자·구분자만 허용, 파싱은 API JSON 용.
 */

/** 허용: 0-9, 쉼표, 세미콜론, 공백(줄바꿈 포함). 그 외 문자 제거. */
export function sanitizeExplicitNodeIdsText(raw: string): string {
  return raw.replace(/[^\d,;\s]/g, '')
}

/** 양의 정수 태그, 중복 제거(입력 순 유지) */
export function parseExplicitNodeIds(text: string): number[] | null {
  const parts = sanitizeExplicitNodeIdsText(text)
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (parts.length === 0) return null
  const out: number[] = []
  const seen = new Set<number>()
  for (const p of parts) {
    const n = Number(p)
    if (!Number.isFinite(n) || !Number.isInteger(n) || n <= 0) return null
    if (seen.has(n)) continue
    seen.add(n)
    out.push(n)
  }
  return out.length > 0 ? out : null
}
