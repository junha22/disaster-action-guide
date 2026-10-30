export function formatDuration(seconds: number): string {
  const total = Math.round(Math.abs(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}시간 ${m}분`
  if (m > 0) return s > 0 ? `${m}분 ${s}초` : `${m}분`
  return `${s}초`
}

export function formatDistance(meters: number): string {
  const abs = Math.abs(meters)
  return abs >= 1000 ? `${(abs / 1000).toFixed(1)}km` : `${Math.round(abs)}m`
}

export function signed(value: number, format: (v: number) => string): string {
  if (Math.round(value) === 0) return '차이 없음'
  return `${value > 0 ? '+' : '−'}${format(value)}`
}

export function formatObserved(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}
