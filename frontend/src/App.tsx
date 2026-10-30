import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpDown, Info, Loader2, Umbrella } from 'lucide-react'

import SearchBar from '@/components/SearchBar'
import RoutePanel from '@/components/RoutePanel'
import WeatherPanel from '@/components/WeatherPanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/lib/api'
import { avoidTypesFor, rainLevel } from '@/lib/level'
import type {
  Alert, AppConfig, Place, RouteRequestBody, RouteResult, StrategyInfo, WeatherInfo, ZoneFeatureCollection,
} from '@/lib/types'

import './App.css'

// maplibre is large; load the map separately.
const MapView = lazy(() => import('@/components/MapView'))

interface WeatherChoice {
  demoMode: boolean
  rain: number
  alert: Alert
}

function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [zones, setZones] = useState<ZoneFeatureCollection | null>(null)
  const [demoPoints, setDemoPoints] = useState<Place[]>([])
  const [loadError, setLoadError] = useState('')
  const [weather, setWeather] = useState<WeatherInfo | null>(null)
  const [weatherLoading, setWeatherLoading] = useState(true)

  const [origin, setOrigin] = useState<Place | null>(null)
  const [destination, setDestination] = useState<Place | null>(null)
  const [strategy, setStrategy] = useState('')
  const [choice, setChoice] = useState<WeatherChoice>({ demoMode: false, rain: 0, alert: 'none' })

  const [result, setResult] = useState<RouteResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [routeError, setRouteError] = useState('')
  const [showBaseline, setShowBaseline] = useState(true)
  const abortRef = useRef<AbortController | null>(null)
  // Level of the latest request; null until the first route is requested.
  const requestedLevel = useRef<number | null>(null)

  useEffect(() => {
    Promise.all([api.appConfig(), api.strategies(), api.riskZones(), api.demoPoints()])
      .then(([cfg, list, zoneData, points]) => {
        setConfig(cfg)
        setStrategies(list)
        setStrategy(cfg.default_strategy)
        setZones(zoneData)
        setDemoPoints(points)
      })
      .catch(e => setLoadError(errorMessage(e, 'API 서버에 연결하지 못했습니다.')))
    api.weather()
      .then(data => {
        setWeather(data)
        // Requirement 2.5: no KMA data -> demo mode.
        if (!data.available) setChoice(c => ({ ...c, demoMode: true }))
      })
      .catch(() => {
        setWeather(null)
        setChoice(c => ({ ...c, demoMode: true }))
      })
      .finally(() => setWeatherLoading(false))
  }, [])

  function levelFor(next: WeatherChoice): number {
    if (!config) return 0
    if (next.demoMode) return rainLevel(next.rain, next.alert, config.level_rules)
    return weather?.available ? weather.level ?? 0 : 0
  }

  function clearResult() {
    abortRef.current?.abort()
    abortRef.current = null
    requestedLevel.current = null
    setBusy(false)
    setResult(null)
    setRouteError('')
  }

  async function runRoute(next: WeatherChoice) {
    if (!origin || !destination || !strategy) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    requestedLevel.current = levelFor(next)
    setBusy(true)
    setRouteError('')
    setResult(null)  // requirement 6.8: clear the previous route first
    const body: RouteRequestBody = {
      origin: { lon: origin.lon, lat: origin.lat },
      destination: { lon: destination.lon, lat: destination.lat },
      strategy,
      weather_override: next.demoMode ? { rn1_mm: next.rain, alert: next.alert } : null,
    }
    try {
      const data = await api.route(body, controller.signal)
      if (abortRef.current === controller) setResult(data)
    } catch (e) {
      if (controller.signal.aborted) return
      setRouteError(errorMessage(e, '경로를 계산하지 못했습니다.'))
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
        setBusy(false)
      }
    }
  }

  // Requirement 6.6: once a route was requested, recalculate once if the level changes.
  function updateChoice(next: WeatherChoice, recalc: boolean) {
    setChoice(next)
    if (recalc && requestedLevel.current !== null && levelFor(next) !== requestedLevel.current) {
      void runRoute(next)
    }
  }

  function pick(setter: (p: Place | null) => void) {
    return (place: Place | null) => {
      setter(place)
      clearResult()
    }
  }

  function swap() {
    setOrigin(destination)
    setDestination(origin)
    clearResult()
  }

  const highlightTypes = useMemo(() => {
    if (result) return result.explanation.avoid_types
    if (!config) return []
    const level = choice.demoMode
      ? rainLevel(choice.rain, choice.alert, config.level_rules)
      : (weather?.available ? weather.level ?? 0 : 0)
    return avoidTypesFor(level, config.level_rules)
  }, [result, config, choice, weather])

  const alternatives = useMemo(() => result?.alternatives.map(a => a.geometry) ?? [], [result])
  const checkedAt = zones?.metadata.data_checked_at ?? '-'

  return (
    <div className="app-shell flex h-dvh flex-col overflow-hidden bg-background text-foreground lg:flex-row-reverse">
      <div className="relative h-[45vh] shrink-0 lg:h-full lg:flex-1">
        <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 size-4 animate-spin" />지도를 불러오는 중</div>}>
          <MapView zones={zones} zoneTypes={config?.zone_types ?? null} highlightTypes={highlightTypes}
            route={result?.route.geometry ?? null} baseline={result?.baseline.geometry ?? null}
            alternatives={alternatives} showBaseline={showBaseline} origin={origin} destination={destination} />
        </Suspense>
      </div>

      <aside className="min-h-0 flex-1 overflow-y-auto border-t lg:w-[400px] lg:flex-none lg:border-t-0 lg:border-r">
        <div className="space-y-5 p-4">
          <header className="space-y-2">
            <h1 className="flex items-center gap-2 text-lg font-bold">
              <Umbrella className="size-5 text-blue-600" />호우 안전 경로 · 광주
            </h1>
            <p className="text-xs text-muted-foreground">
              비가 많이 올수록 지하차도 → 침수 이력 도로 → 하천변을 단계적으로 피하는 자동차 경로입니다.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {zones?.metadata.has_dummy && (
                <Badge variant="outline" className="border-orange-400 text-orange-700">위험 구역: 더미 데이터</Badge>
              )}
              {config?.search_mode === 'demo' && <Badge variant="secondary">데모 지점 검색</Badge>}
            </div>
          </header>

          {loadError && (
            <p role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              {loadError}
            </p>
          )}

          <section className="space-y-3" aria-label="출발지와 목적지">
            <SearchBar id="origin" label="출발지" value={origin} onChange={pick(setOrigin)} demoPoints={demoPoints}
              bbox={config?.service_area_bbox ?? null} allowCurrentLocation />
            <div className="flex justify-center">
              <Button type="button" variant="ghost" size="sm" onClick={swap} disabled={!origin && !destination}>
                <ArrowUpDown />출발·목적지 바꾸기
              </Button>
            </div>
            <SearchBar id="destination" label="목적지" value={destination} onChange={pick(setDestination)}
              demoPoints={demoPoints} bbox={config?.service_area_bbox ?? null} />
          </section>

          <WeatherPanel config={config} weather={weather} loading={weatherLoading} demoMode={choice.demoMode}
            onDemoModeChange={on => updateChoice({ ...choice, demoMode: on }, true)}
            rain={choice.rain}
            onRainChange={rain => setChoice(c => ({ ...c, rain }))}
            onRainCommit={rain => updateChoice({ ...choice, rain }, true)}
            alert={choice.alert}
            onAlertChange={alert => updateChoice({ ...choice, alert }, true)} />

          <RoutePanel config={config} strategies={strategies} strategy={strategy} onStrategyChange={setStrategy}
            canSubmit={Boolean(origin && destination && strategy)} busy={busy}
            onSubmit={() => void runRoute(choice)} result={result} error={routeError}
            showBaseline={showBaseline} onShowBaselineChange={setShowBaseline} />

          <footer className="space-y-1.5 rounded-lg bg-muted/60 p-3 text-xs leading-5" role="note">
            <p className="flex gap-1.5 font-medium">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              이 서비스는 실제 도로 통제와 침수 여부를 확인하지 않습니다. 지하차도 통제, 재난문자, 경찰·지자체 안내를 먼저 따르세요.
            </p>
            <p className="text-muted-foreground">
              실시간 교통을 반영하지 않습니다. 위험 구역 데이터 기준일 {checkedAt}
              {zones?.metadata.has_dummy ? ' · 더미 데이터 — 실제 자료 아님' : ''}.
            </p>
            <p className="text-muted-foreground">
              출발지·목적지와 검색어는 서버에 저장하지 않습니다. 지도 타일은 OpenFreeMap에서 받습니다.
            </p>
          </footer>
        </div>
      </aside>
    </div>
  )
}

export default App
