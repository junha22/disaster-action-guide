export type ZoneType = 'underpass' | 'flood_history' | 'riverside'
export type Alert = 'none' | 'advisory' | 'warning'
export type LonLat = [number, number]

export interface ZoneTypeInfo {
  label: string
  color: string
  weight: number
}

export interface LevelRules {
  thresholds_mm: number[]
  avoid_by_level: Record<string, ZoneType[]>
  alert_min_level: { advisory: number; warning: number }
}

export interface AppConfig {
  search_mode: 'kakao' | 'demo'
  service_area_bbox: [number, number, number, number]
  zone_types: Record<ZoneType, ZoneTypeInfo>
  level_rules: LevelRules
  default_strategy: string
}

export interface StrategyInfo {
  name: string
  label: string
  description: string
  default: boolean
  params: string[]
}

export interface Place {
  id: string
  name: string
  address: string
  lon: number
  lat: number
  selectable: boolean
  reason: string | null
  source: 'kakao' | 'demo' | 'gps'
}

export interface SearchResult {
  mode: 'kakao' | 'demo'
  notice: string | null
  items: Place[]
}

export interface WeatherInfo {
  available: boolean
  source: 'kma' | 'unavailable'
  rn1_mm: number | null
  alert: Alert
  alert_label: string
  alert_status: 'ok' | 'failed'
  level: number | null
  observed_at: string | null
  message: string | null
}

export interface LineGeometry {
  type: 'LineString'
  coordinates: LonLat[]
}

export interface OsrmRoute {
  geometry: LineGeometry
  distance: number
  duration: number
  weight: number
  weight_name: string
  legs: unknown[]
}

export interface ZoneRef {
  id: string
  name: string
  type: ZoneType
}

export interface PassedZone extends ZoneRef {
  length_m: number
}

export type PlanStatus =
  | 'baseline' | 'no_avoid_level' | 'nothing_on_route' | 'avoided' | 'avoid_failed' | 'ranked'

export interface Explanation {
  status: PlanStatus
  level: number
  avoid_types: ZoneType[]
  avoided_zones: ZoneRef[]
  passed_zones: PassedZone[]
  baseline_passed_zones: PassedZone[]
  added_duration_s: number
  added_distance_m: number
  message: string
  warning: string | null
  failure_reason: string | null
}

export interface RouteMetrics {
  label: string
  duration_s: number
  distance_m: number
  exposure_score: number
  exposure_by_type_m: Record<ZoneType, number>
}

export interface RouteWeather {
  source: 'kma' | 'demo' | 'unavailable'
  rn1_mm: number
  alert: Alert
  level: number
  observed_at: string | null
  real_weather_applied: boolean
  alert_status: string
}

export interface RouteResult {
  strategy: { name: string; label: string }
  route: OsrmRoute
  alternatives: OsrmRoute[]
  baseline: OsrmRoute
  explanation: Explanation
  metrics: { route: RouteMetrics; baseline: RouteMetrics; alternatives: RouteMetrics[] }
  weather: RouteWeather
}

// POST /api/route/explain: finished facts only, no coordinates (requirement 8).
export interface ExplainSide {
  duration_s: number
  zones: { id: string; length_m: number }[]
}

export interface RouteExplainBody {
  status: PlanStatus
  level: number
  alert: Alert
  route: ExplainSide
  baseline: ExplainSide
}

export interface RouteExplainResult {
  text: string
  source: 'ai' | 'template'
  reason: string | null
  cached: boolean
}

export interface RouteRequestBody {
  origin: { lon: number; lat: number }
  destination: { lon: number; lat: number }
  strategy: string
  weather_override: { rn1_mm: number; alert: Alert } | null
}

export interface ZoneProperties extends ZoneRef {
  active: boolean
  source_name: string
  source_url: string
  checked_at: string
  is_dummy: boolean
  note: string
}

export interface ZoneFeatureCollection {
  type: 'FeatureCollection'
  features: { type: 'Feature'; properties: ZoneProperties; geometry: unknown }[]
  metadata: { has_dummy: boolean; data_checked_at: string | null; count: number }
}
