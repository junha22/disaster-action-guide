import type { Alert, AppConfig, LevelRules, ZoneGroup, ZoneType } from './types'

// Same rule as backend app/config.rain_level (design.md 3.1), using /api/app-config values.
export function rainLevel(rn1: number, alert: Alert, rules: LevelRules): number {
  let level = rules.thresholds_mm.filter(t => rn1 >= t).length
  if (alert === 'advisory' || alert === 'warning') level = Math.max(level, rules.alert_min_level[alert])
  return Math.min(level, 3)
}

// Avoidance groups ("underpass", "flood_history.high", ...) of a level, hard + soft (design.md 5.8).
export function avoidGroupsFor(level: number, rules: LevelRules): ZoneGroup[] {
  return rules.avoid_by_level[String(level)] ?? []
}

export function softGroupsFor(level: number, rules: LevelRules): ZoneGroup[] {
  return rules.soft_by_level?.[String(level)] ?? []
}

export function groupsOfType(type: ZoneType, config: Pick<AppConfig, 'zone_groups'>): ZoneGroup[] {
  return Object.keys(config.zone_groups).filter(g => config.zone_groups[g].type === type)
}

// "all" when every group of the type is avoided, "some" when only some tiers are, else "none".
export function typeCoverage(type: ZoneType, groups: ZoneGroup[], config: Pick<AppConfig, 'zone_groups'>) {
  const mine = groupsOfType(type, config)
  const hit = mine.filter(g => groups.includes(g)).length
  return hit === 0 ? 'none' : hit === mine.length ? 'all' : 'some'
}

// "지하차도(반드시), 침수 이력 우선 회피(반드시), 침수 이력 일반·주변보다 높은 편(되도록)".
// A whole type is named once when all of its tiers share the same rule.
export function avoidRuleText(level: number, config: Pick<AppConfig, 'zone_groups' | 'zone_types' | 'level_rules'>): string {
  const rules = config.level_rules
  const soft = new Set(softGroupsFor(level, rules))
  const avoid = avoidGroupsFor(level, rules)
  const parts: string[] = []
  for (const type of Object.keys(config.zone_types) as ZoneType[]) {
    const label = config.zone_types[type].label
    const mine = groupsOfType(type, config).filter(g => avoid.includes(g))
    if (mine.length === 0) continue
    const hardOnes = mine.filter(g => !soft.has(g))
    const softOnes = mine.filter(g => soft.has(g))
    const whole = mine.length === groupsOfType(type, config).length
    for (const [members, rule] of [[hardOnes, '반드시'], [softOnes, '되도록']] as const) {
      if (members.length === 0) continue
      const tiers = members.map(g => config.zone_groups[g].tier_label).filter(Boolean)
      const name = (whole && members.length === mine.length) || tiers.length === 0
        ? label
        : `${label} ${tiers.join('·')}`
      parts.push(`${name}(${rule})`)
    }
  }
  return parts.length ? parts.join(', ') : '없음'
}

export const ALERT_LABELS: Record<Alert, string> = {
  none: '없음',
  advisory: '호우주의보',
  warning: '호우경보',
}
