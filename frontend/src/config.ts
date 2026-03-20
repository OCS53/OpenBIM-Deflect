/** 백엔드 API 원점 (슬래시 없음). `.env` 의 `VITE_API_URL` 또는 런타임 오버라이드. */
export function defaultApiBase(): string {
  const v = import.meta.env.VITE_API_URL
  if (typeof v !== 'string' || !v.trim()) return ''
  return v.trim().replace(/\/$/, '')
}

export function joinApiUrl(base: string, path: string): string {
  const b = base.replace(/\/$/, '')
  const p = path.startsWith('/') ? path : `/${path}`
  return `${b}${p}`
}
