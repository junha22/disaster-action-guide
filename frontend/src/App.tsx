import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpDown, Info, Loader2, Play } from 'lucide-react'

import DriveMode from '@/components/DriveMode'
import RoutePanel from '@/components/RoutePanel'
import RouteResultCard from '@/components/RouteResultCard'
import SearchBar from '@/components/SearchBar'
import WeatherCanvas from '@/components/WeatherCanvas'
import WeatherPanel from '@/components/WeatherPanel'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/lib/api'
import { avoidGroupsFor, rainLevel } from '@/lib/level'
import { useIsWide } from '@/lib/media'
import { currentTimeOfDay, weatherScene, type TimeOfDay } from '@/lib/scene'
import { dummyNotice } from '@/lib/zones'
import type {
  Alert, AppConfig, GuidanceStep, Place, RouteRequestBody, RouteResult, StrategyInfo, WeatherInfo, ZoneFeatureCollection,
} from '@/lib/types'

import './App.css'

// maplibre is large; load the map separately.
const MapView = lazy(() => import('@/components/MapView'))

interface WeatherChoice {
  demoMode: boolean
  rain: number
  alert: Alert
}

const DEMO_ROUTE = { origin: '광주송정역', destination: '광주역' }
const CLOCK_CHECK_MS = 5 * 60 * 1000

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
  const isWide = useIsWide()
  const [clockTime, setClockTime] = useState<TimeOfDay>(() => currentTimeOfDay())
  const [timeChoice, setTimeChoice] = useState<TimeOfDay | null>(null)
  const [driveSteps, setDriveSteps] = useState<GuidanceStep[] | null>(null)
  const [startingDrive, setStartingDrive] = useState(false)

  useEffect(() => {
    const timer = window.setInterval(() => setClockTime(currentTimeOfDay()), CLOCK_CHECK_MS)
    return () => window.clearInterval(timer)
  }, [])

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

  async function runRoute(next: WeatherChoice, from = origin, to = destination) {
    if (!from || !to || !strategy) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    requestedLevel.current = levelFor(next)
    setBusy(true)
    setRouteError('')
    setResult(null)  // requirement 6.8: clear the previous route first
    const body: RouteRequestBody = {
      origin: { lon: from.lon, lat: from.lat },
      destination: { lon: to.lon, lat: to.lat },
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

  // Avoidance groups drawn strongly on the map (design.md 5.8): from the result, else the current level.
  const highlightGroups = useMemo(() => {
    if (result) return result.explanation.avoid_groups
    if (!config) return []
    const level = choice.demoMode
      ? rainLevel(choice.rain, choice.alert, config.level_rules)
      : (weather?.available ? weather.level ?? 0 : 0)
    return avoidGroupsFor(level, config.level_rules)
  }, [result, config, choice, weather])

  const alternatives = useMemo(() => result?.alternatives.map(a => a.geometry) ?? [], [result])
  const passedZoneIds = useMemo(() => result?.explanation.passed_zones.map(z => z.id) ?? [], [result])
  const checkedAt = zones?.metadata.data_checked_at ?? '-'

  const sceneRain = choice.demoMode ? choice.rain : (weather?.available ? weather.rn1_mm ?? 0 : 0)
  const sceneLevel = levelFor(choice)
  const sceneTime = timeChoice ?? clockTime
  const scene = useMemo(() => weatherScene(sceneRain, sceneLevel, sceneTime), [sceneRain, sceneLevel, sceneTime])
  const demoOrigin = demoPoints.find(p => p.name === DEMO_ROUTE.origin)
  const demoDestination = demoPoints.find(p => p.name === DEMO_ROUTE.destination)

  function startDemo() {
    if (!demoOrigin || !demoDestination) return
    const next = { ...choice, demoMode: true }
    setOrigin(demoOrigin)
    setDestination(demoDestination)
    setChoice(next)
    void runRoute(next, demoOrigin, demoDestination)
  }

  async function startDrive() {
    if (!result) return
    setStartingDrive(true)
    try {
      const { steps } = await api.guidance(result.route.geometry.coordinates)
      setDriveSteps(steps)
    } catch {
      // Guidance is an extra on top of the route: drive with the route line alone.
      setDriveSteps([])
    } finally {
      setStartingDrive(false)
    }
  }

  if (result && driveSteps) {
    return <DriveMode result={result} steps={driveSteps} scene={scene} zones={zones} destination={destination}
      onExit={() => setDriveSteps(null)} />
  }

  const resultCard = result && (
    <RouteResultCard config={config} result={result} showBaseline={showBaseline}
      onShowBaselineChange={setShowBaseline} starting={startingDrive} onStartDrive={() => void startDrive()} />
  )

  return (
    <div className="app-shell dark flex h-dvh flex-col gap-3 overflow-hidden p-0 text-foreground lg:flex-row-reverse lg:p-3">
      <div className="scene" aria-hidden="true"><WeatherCanvas spec={scene} variant="page" /></div>

      <div className="map-frame relative h-[45vh] shrink-0 lg:h-full lg:flex-1">
        <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 size-4 animate-spin" />지도를 불러오는 중</div>}>
          <MapView zones={zones} config={config ?? null} highlightGroups={highlightGroups}
            passedZoneIds={passedZoneIds} floatingCard={isWide && Boolean(result)}
            route={result?.route.geometry ?? null} baseline={result?.baseline.geometry ?? null}
            alternatives={alternatives} showBaseline={showBaseline} origin={origin} destination={destination} />
        </Suspense>
        {/* The tint stays light: the route and zones underneath must remain readable in any weather. */}
        <div className="map-weather" style={{ backgroundColor: `rgb(6 10 20 / ${scene.mapTint})` }} aria-hidden="true">
          <WeatherCanvas spec={scene} variant="map" />
        </div>
        {isWide && resultCard && <div className="result-float glass-card">{resultCard}</div>}
      </div>

      <aside className="relative min-h-0 flex-1 overflow-y-auto lg:w-[400px] lg:flex-none">
        <div className="space-y-3 p-3 lg:p-0 lg:pr-1">
          {loadError && (
            <p role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              {loadError}
            </p>
          )}

          <WeatherPanel config={config} weather={weather} loading={weatherLoading} scene={scene} rainShown={sceneRain}
            dummyZonesNotice={dummyNotice(zones, config?.zone_types)} timeChoice={timeChoice} onTimeChoiceChange={setTimeChoice}
            demoMode={choice.demoMode}
            onDemoModeChange={on => updateChoice({ ...choice, demoMode: on }, true)}
            rain={choice.rain}
            onRainChange={rain => setChoice(c => ({ ...c, rain }))}
            onRainCommit={rain => updateChoice({ ...choice, rain }, true)}
            alert={choice.alert}
            onAlertChange={alert => updateChoice({ ...choice, alert }, true)} />

          <div className="glass-card space-y-3">
            {demoOrigin && demoDestination && (
              <Button type="button" variant="secondary" className="w-full" disabled={busy} onClick={startDemo}>
                <Play />시연 경로 보기 · {DEMO_ROUTE.origin} → {DEMO_ROUTE.destination}
              </Button>
            )}
            <section className="relative space-y-2" aria-label="출발지와 목적지">
              <Button type="button" variant="ghost" size="icon-sm" className="absolute top-0 right-0 z-10"
                aria-label="출발·목적지 바꾸기" title="출발·목적지 바꾸기" onClick={swap} disabled={!origin && !destination}>
                <ArrowUpDown />
              </Button>
              <SearchBar id="origin" label="출발지" value={origin} onChange={pick(setOrigin)} demoPoints={demoPoints}
                bbox={config?.service_area_bbox ?? null} allowCurrentLocation />
              <SearchBar id="destination" label="목적지" value={destination} onChange={pick(setDestination)}
                demoPoints={demoPoints} bbox={config?.service_area_bbox ?? null} />
            </section>

            <RoutePanel strategies={strategies} strategy={strategy} onStrategyChange={setStrategy}
              canSubmit={Boolean(origin && destination && strategy)} busy={busy}
              onSubmit={() => void runRoute(choice)} error={routeError} />
          </div>

          {!isWide && resultCard && <div className="glass-card">{resultCard}</div>}

          <footer className="glass-card space-y-1.5 text-xs leading-5" role="note">
            <p className="text-muted-foreground">
              비가 많이 올수록 지하차도 → 침수 이력 도로 → 하천변을 단계적으로 피하는 자동차 경로입니다.
            </p>
            <p className="flex gap-1.5 font-medium">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              이 서비스는 실제 도로 통제와 침수 여부를 확인하지 않습니다. 지하차도 통제, 재난문자, 경찰·지자체 안내를 먼저 따르세요.
            </p>
            <p className="text-muted-foreground">
              실시간 교통을 반영하지 않습니다. 위험 구역 데이터 기준일 {checkedAt}
              {dummyNotice(zones, config?.zone_types) ? ` · ${dummyNotice(zones, config?.zone_types)}` : ''}.
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
