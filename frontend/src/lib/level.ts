import type { Alert, LevelRules, ZoneType } from './types'

// Same rule as backend app/config.rain_level (design.md 3.1), using /api/app-config values.
export function rainLevel(rn1: number, alert: Alert, rules: LevelRules): number {
  let level = rules.thresholds_mm.filter(t => rn1 >= t).length
  if (alert === 'advisory' || alert === 'warning') level = Math.max(level, rules.alert_min_level[alert])
  return Math.min(level, 3)
}

export function avoidTypesFor(level: number, rules: LevelRules): ZoneType[] {
  return rules.avoid_by_level[String(level)] ?? []
}

export function softTypesFor(level: number, rules: LevelRules): ZoneType[] {
  return rules.soft_by_level?.[String(level)] ?? []
}

export const ALERT_LABELS: Record<Alert, string> = {
  none: '없음',
  advisory: '호우주의보',
  warning: '호우경보',
}
