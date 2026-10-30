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
