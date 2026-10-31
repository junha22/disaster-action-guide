// All calls use relative /api/ paths. Coordinates and search terms go in POST bodies only.
import type {
  AppConfig, GuidanceStep, LonLat, ParkingCheck, Place, RerouteExplainBody, RerouteExplainResult, RerouteRequestBody, RerouteResult,
  RouteExplainBody, RouteExplainResult, RouteRequestBody, RouteResult, SearchResult, WeatherInfo,
  WeatherRegion, ZoneFeatureCollection,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    let message = `요청 실패 (HTTP ${response.status})`
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') message = detail
      else if (response.status === 422) message = '입력값을 확인하세요.'
    }
    throw new ApiError(response.status, message)
  }
  return body as T
}

function post<T>(url: string, data: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    signal,
  })
}

export const api = {
  appConfig: () => request<AppConfig>('/api/app-config'),
  riskZones: () => request<ZoneFeatureCollection>('/api/risk-zones'),
  demoPoints: () => request<Place[]>('/api/demo-points'),
  weather: (signal?: AbortSignal) => request<WeatherInfo>('/api/weather', { signal }),
  weatherAt: (point: { lon: number; lat: number }, signal?: AbortSignal) => post<WeatherInfo>('/api/weather', point, signal),
  weatherRegions: () => request<WeatherRegion[]>('/api/weather/regions'),
  search: (query: string) => post<SearchResult>('/api/search', { query }),
  route: (body: RouteRequestBody, signal?: AbortSignal) => post<RouteResult>('/api/route', body, signal),
  guidance: (coordinates: LonLat[]) => post<{ steps: GuidanceStep[] }>('/api/route/guidance', { coordinates }),
  explainRoute: (body: RouteExplainBody, signal?: AbortSignal) =>
    post<RouteExplainResult>('/api/route/explain', body, signal),
  reroute: (body: RerouteRequestBody, signal?: AbortSignal) => post<RerouteResult>('/api/route/reroute', body, signal),
  explainReroute: (body: RerouteExplainBody, signal?: AbortSignal) =>
    post<RerouteExplainResult>('/api/route/reroute/explain', body, signal),
  parkingCheck: (body: { lon: number; lat: number; demo: boolean }, signal?: AbortSignal) =>
    post<ParkingCheck>('/api/parking/check', body, signal),
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}
