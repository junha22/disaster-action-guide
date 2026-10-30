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

// The zones of the current route the driver is asked about.
export function avoidIds(decision: RerouteResult): string[] {
  return [...decision.current.hard_zone_ids, ...decision.current.soft_zone_ids]
}

export function avoidCount(decision: RerouteResult): number {
  return avoidIds(decision).length
}
