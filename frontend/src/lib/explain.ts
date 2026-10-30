import type { PassedZone, PlanStatus, RouteExplainBody, RouteResult } from './types'

// These statuses already show a fixed message (requirement 6.5); no explanation request.
const FIXED_STATUSES: ReadonlySet<PlanStatus> = new Set(['baseline', 'no_avoid_level', 'nothing_on_route'])

export function needsExplanation(result: RouteResult): boolean {
  return !FIXED_STATUSES.has(result.explanation.status)
}

const zones = (list: PassedZone[]) => list.map(z => ({ id: z.id, length_m: z.length_m }))

// Facts the route logic already computed. Coordinates are not sent.
export function explainBody(result: RouteResult): RouteExplainBody {
  const e = result.explanation
  return {
    status: e.status,
    level: e.level,
    alert: result.weather.alert,
    route: { duration_s: result.metrics.route.duration_s, zones: zones(e.passed_zones) },
    baseline: { duration_s: result.metrics.baseline.duration_s, zones: zones(e.baseline_passed_zones) },
  }
}
