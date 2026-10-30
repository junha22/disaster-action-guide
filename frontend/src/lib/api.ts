// All calls use relative /api/ paths. Coordinates and search terms go in POST bodies only.
import type {
  AppConfig, Place, RouteRequestBody, RouteResult, SearchResult, StrategyInfo, WeatherInfo,
  ZoneFeatureCollection,
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
  strategies: () => request<StrategyInfo[]>('/api/strategies'),
  riskZones: () => request<ZoneFeatureCollection>('/api/risk-zones'),
  demoPoints: () => request<Place[]>('/api/demo-points'),
  weather: () => request<WeatherInfo>('/api/weather'),
  search: (query: string) => post<SearchResult>('/api/search', { query }),
  route: (body: RouteRequestBody, signal?: AbortSignal) => post<RouteResult>('/api/route', body, signal),
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}
