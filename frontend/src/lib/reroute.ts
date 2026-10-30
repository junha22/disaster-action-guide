import type { PassedZone, RainState, RerouteExplainBody, RerouteResult } from './types'

const zones = (list: PassedZone[]) => list.map(z => ({ id: z.id, length_m: z.length_m }))

// Facts the route logic already computed. Coordinates are not sent.
export function rerouteExplainBody(decision: RerouteResult, previous: RainState): RerouteExplainBody {
  return {
    action: decision.action,
    previous,
    now: { rn1_mm: decision.weather.rn1_mm, alert: decision.weather.alert },
    current: { duration_s: decision.current.duration_s, zones: zones(decision.current.zones) },
    candidate: { duration_s: decision.candidate.duration_s, zones: zones(decision.candidate.zones) },
    hard_groups: decision.hard_groups,
    soft_groups: decision.soft_groups,
  }
}

// The zones the driver is asked about, for a sentence: "피할 구간 3곳".
export function avoidCount(decision: RerouteResult): number {
  return decision.current.hard_zone_ids.length + decision.current.soft_zone_ids.length
}

// What is read aloud while driving: two short sentences from the computed numbers, not the
// longer AI wording on the card (which stays on screen). "비가 강해졌어요" was already spoken.
export function spokenRerouteSummary(decision: RerouteResult): string {
  const before = avoidCount(decision)
  const after = decision.candidate.hard_zone_ids.length + decision.candidate.soft_zone_ids.length
  const zones = after === 0
    ? `바꾸면 피할 구간 ${before}곳을 모두 지나지 않아요.`
    : `바꾸면 피할 구간이 ${before}곳에서 ${after}곳으로 줄어요.`
  const minutes = Math.round((decision.candidate.duration_s - decision.current.duration_s) / 60)
  const time = minutes > 0 ? `${minutes}분 더 걸려요.` : minutes < 0 ? `${-minutes}분 덜 걸려요.` : '시간은 거의 같아요.'
  return `${zones} ${time}`
}
