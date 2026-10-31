export type ZoneType = 'underpass' | 'flood_history' | 'riverside'
// Avoidance group: a type, or "flood_history.high" etc. for flood terrain tiers (design.md 5.8).
export type ZoneGroup = string
export type Alert = 'none' | 'advisory' | 'warning'
export type LonLat = [number, number]

export interface ZoneTypeInfo {
  label: string
  color: string
  weight: number
}

export interface ZoneGroupInfo {
  type: ZoneType
  tier: string | null
  label: string             // "침수 이력(우선 회피)"
  tier_label: string | null // "우선 회피"
}

export interface LevelRules {
  thresholds_mm: number[]
  avoid_by_level: Record<string, ZoneGroup[]>  // hard + soft
  hard_by_level: Record<string, ZoneGroup[]>   // 반드시 피함
  soft_by_level: Record<string, ZoneGroup[]>   // 되도록 피함
  alert_min_level: { advisory: number; warning: number }
}

export interface AppConfig {
  search_mode: 'kakao' | 'demo'
  service_area_bbox: [number, number, number, number]
  zone_types: Record<ZoneType, ZoneTypeInfo>
  zone_groups: Record<ZoneGroup, ZoneGroupInfo>
  level_rules: LevelRules
  default_strategy: string
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
  region?: string
  routable?: boolean
  station?: string | null
  message: string | null
}

// A place the weather can be read at: Gwangju and Jeonnam (GET /api/weather/regions).
export interface WeatherRegion {
  id: string
  name: string
  group: string
  lon: number
  lat: number
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
  group: ZoneGroup
  length_m: number
}

export type PlanStatus =
  | 'baseline' | 'no_avoid_level' | 'nothing_on_route' | 'avoided' | 'partially_avoided' | 'avoid_failed'
  | 'ranked'

export interface Explanation {
  status: PlanStatus
  level: number
  avoid_types: ZoneType[]  // types with at least one avoided group
  avoid_groups: ZoneGroup[]
  hard_groups: ZoneGroup[]
  soft_groups: ZoneGroup[]
  clear_option: { added_duration_s: number; added_distance_m: number } | null
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
  region: string | null
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
  hard_groups: ZoneGroup[]
  soft_groups: ZoneGroup[]
}

export interface RouteExplainResult {
  text: string
  source: 'ai' | 'template'
  reason: string | null
  cached: boolean
}

export interface RainState {
  rn1_mm: number
  alert: Alert
}

export type RerouteAction = 'recommend' | 'keep' | 'no_better'

// POST /api/route/reroute: the rain got worse during a drive.
export interface RerouteRequestBody {
  position: { lon: number; lat: number }
  destination: { lon: number; lat: number }
  heading: number
  remaining: LonLat[]
  remaining_duration_s: number
  previous: RainState
  weather_override: RainState | null
}

export interface RerouteSide {
  duration_s: number
  distance_m: number
  zones: PassedZone[]
  hard_zone_ids: string[]
  soft_zone_ids: string[]
}

export interface RerouteResult {
  action: RerouteAction
  status: PlanStatus
  hard_groups: ZoneGroup[]
  soft_groups: ZoneGroup[]
  previous_level: number
  weather: RouteWeather
  route: OsrmRoute
  current: RerouteSide
  candidate: RerouteSide
  avoided_zone_ids: string[]
  text: string
}

export interface RerouteExplainBody {
  action: RerouteAction
  previous: RainState
  now: RainState
  current: ExplainSide
  candidate: ExplainSide
  hard_groups: ZoneGroup[]
  soft_groups: ZoneGroup[]
}

export type RerouteExplainResult = RouteExplainResult

export interface RouteRequestBody {
  origin: { lon: number; lat: number }
  destination: { lon: number; lat: number }
  strategy: string
  weather_override: { rn1_mm: number; alert: Alert } | null
}

export type StepKind =
  | 'depart' | 'arrive' | 'straight' | 'slight_left' | 'left' | 'sharp_left'
  | 'slight_right' | 'right' | 'sharp_right' | 'uturn' | 'merge' | 'roundabout'

export interface GuidanceStep {
  kind: StepKind
  name: string
  distance_m: number
  duration_s: number
}

export interface ZoneProperties extends ZoneRef {
  active: boolean
  source_name: string
  source_url: string
  checked_at: string
  is_dummy: boolean
  note: string
  group: ZoneGroup
  risk_tier: string | null
  tier_reason: string | null
  // flood_history only (DEM elevation, risk_zones_guide(DEM).md); null when unknown
  flood_count?: number | null
  elev_m?: number | null
  low_pct?: number | null
  above_local_min_m?: number | null
  elev_status?: string | null
}

export interface ZoneFeatureCollection {
  type: 'FeatureCollection'
  features: { type: 'Feature'; properties: ZoneProperties; geometry: unknown }[]
  metadata: { has_dummy: boolean; data_checked_at: string | null; count: number }
}
