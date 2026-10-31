import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpDown, Info, Loader2 } from 'lucide-react'

import DriveMode, { type DriveExit } from '@/components/DriveMode'
import RoutePanel from '@/components/RoutePanel'
import RouteResultCard from '@/components/RouteResultCard'
import SearchBar from '@/components/SearchBar'
import WeatherCanvas from '@/components/WeatherCanvas'
import WeatherPanel from '@/components/WeatherPanel'
import { Button } from '@/components/ui/button'
import { ApiError, api, errorMessage } from '@/lib/api'
import { formatDistance } from '@/lib/format'
import { avoidGroupsFor, rainLevel } from '@/lib/level'
import { locate } from '@/lib/location'
import { mapThemeFor } from '@/lib/mapTheme'
import { useIsWide } from '@/lib/media'
import { currentTimeOfDay, weatherScene, type TimeOfDay } from '@/lib/scene'
import { dummyNotice } from '@/lib/zones'
import type {
  Alert, AppConfig, GuidanceStep, Place, RouteRequestBody, RouteResult, WeatherInfo, WeatherRegion,
  ZoneFeatureCollection,
} from '@/lib/types'

import './App.css'

// maplibre is large; load the map separately.
const MapView = lazy(() => import('@/components/MapView'))

interface WeatherChoice {
  demoMode: boolean
  rain: number
  alert: Alert
}

const CLOCK_CHECK_MS = 5 * 60 * 1000
const DEFAULT_WEATHER_PLACE = 'gwangju'
// The stations renew every minute and the server keeps a table for 2 minutes.
const WEATHER_REFRESH_MS = 2 * 60 * 1000
// One forecast grid cell. A position this rough can land in the wrong cell or county.
const COARSE_WEATHER_M = 5000

function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [zones, setZones] = useState<ZoneFeatureCollection | null>(null)
  const [demoPoints, setDemoPoints] = useState<Place[]>([])
  const [loadError, setLoadError] = useState('')
  const [weather, setWeather] = useState<WeatherInfo | null>(null)
  const [weatherLoading, setWeatherLoading] = useState(true)
  const [weatherRegions, setWeatherRegions] = useState<WeatherRegion[]>([])
  const [weatherPlace, setWeatherPlace] = useState(DEFAULT_WEATHER_PLACE)  // a region id, or 'current'
  const [locating, setLocating] = useState(false)
  const [locationNote, setLocationNote] = useState('')
  const weatherAbort = useRef<AbortController | null>(null)
  const weatherPoint = useRef<{ lon: number; lat: number } | null>(null)

  const [origin, setOrigin] = useState<Place | null>(null)
  const [destination, setDestination] = useState<Place | null>(null)
  const strategy = config?.default_strategy ?? ''
  const [choice, setChoice] = useState<WeatherChoice>({ demoMode: false, rain: 0, alert: 'none' })

  const [result, setResult] = useState<RouteResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [routeError, setRouteError] = useState('')
  const [showBaseline, setShowBaseline] = useState(true)
  const abortRef = useRef<AbortController | null>(null)
  // Level of the latest request; null until the first route is requested.
  const requestedLevel = useRef<number | null>(null)
  const isWide = useIsWide()
  const asideRef = useRef<HTMLElement>(null)
  const scrollToResult = useRef(false)
  // Keeps the phone layout from jumping while a new result replaces the old one.
  const phoneCardRef = useRef<HTMLDivElement>(null)
  const [loadingCardHeight, setLoadingCardHeight] = useState(0)

  useEffect(() => {
    if (!result || isWide || !scrollToResult.current) return
    scrollToResult.current = false
    asideRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [result, isWide])
  const [clockTime, setClockTime] = useState<TimeOfDay>(() => currentTimeOfDay())
  const [timeChoice, setTimeChoice] = useState<TimeOfDay | null>(null)
  const [driveSteps, setDriveSteps] = useState<GuidanceStep[] | null>(null)
  const [startingDrive, setStartingDrive] = useState(false)

  useEffect(() => {
    const timer = window.setInterval(() => setClockTime(currentTimeOfDay()), CLOCK_CHECK_MS)
    return () => window.clearInterval(timer)
  }, [])

  const loadWeather = useCallback((point: { lon: number; lat: number } | null, place: string, note = '') => {
    weatherAbort.current?.abort()
    const controller = new AbortController()
    weatherAbort.current = controller
    weatherPoint.current = point
    const request = point ? api.weatherAt(point, controller.signal) : api.weather(controller.signal)
    request
      .then(data => {
        setWeather(data)
        setWeatherPlace(place)
        setLocationNote(note)
        // Requirement 2.5: no KMA data -> demo mode.
        if (!data.available) setChoice(c => ({ ...c, demoMode: true }))
      })
      .catch(e => {
        if (controller.signal.aborted) return
        if (e instanceof ApiError && e.status === 422) {
          setLocationNote('현재 위치가 광주·전남 밖이에요. 목록에서 지역을 고르세요.')
          return
        }
        setWeather(null)
        setChoice(c => ({ ...c, demoMode: true }))
      })
      .finally(() => {
        if (weatherAbort.current === controller) setWeatherLoading(false)
      })
  }, [])

  const locateWeather = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationNote('이 브라우저에서는 현재 위치를 쓸 수 없어요. 목록에서 지역을 고르세요.')
      return
    }
    setLocating(true)
    locate(
      ({ coords }) => {
        setLocating(false)
        setWeatherLoading(true)
        loadWeather({ lon: coords.longitude, lat: coords.latitude }, 'current', coords.accuracy > COARSE_WEATHER_M
          ? `위치 오차가 약 ${formatDistance(coords.accuracy)}예요. 실제 지역과 다를 수 있어요.` : '')
      },
      () => {
        setLocating(false)
        setLocationNote('현재 위치를 가져오지 못했어요. 목록에서 지역을 고르세요.')
      },
    )
  }, [loadWeather])

  // A failed refresh keeps the last reading: it must not push a working screen into demo mode.
  const driving = driveSteps !== null
  useEffect(() => {
    if (driving) return  // the driving screen reads the weather at the car
    const read = (point: { lon: number; lat: number } | null) => {
      const request = point ? api.weatherAt(point) : api.weather()
      request
        .then(data => {
          if (data.available && weatherPoint.current === point) setWeather(data)
        })
        .catch(() => undefined)
    }
    const timer = window.setInterval(() => {
      if (weatherPlace !== 'current') {
        read(weatherPoint.current)
        return
      }
      locate(({ coords }) => {
        weatherPoint.current = { lon: coords.longitude, lat: coords.latitude }
        read(weatherPoint.current)
      }, () => read(weatherPoint.current))
    }, WEATHER_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [driving, weatherPlace])

  function pickWeatherPlace(value: string) {
    setLocationNote('')
    if (value === 'current') {
      locateWeather()
      return
    }
    const region = weatherRegions.find(r => r.id === value)
    if (!region) return
    setWeatherPlace(region.id)
    setWeatherLoading(true)
    loadWeather({ lon: region.lon, lat: region.lat }, region.id)
  }

  useEffect(() => {
    Promise.all([api.appConfig(), api.riskZones(), api.demoPoints()])
      .then(([cfg, zoneData, points]) => {
        setConfig(cfg)
        setZones(zoneData)
        setDemoPoints(points)
      })
      .catch(e => setLoadError(errorMessage(e, 'API 서버에 연결하지 못했습니다.')))
    api.weatherRegions().then(setWeatherRegions).catch(() => undefined) // the place stays the default one
    loadWeather(null, DEFAULT_WEATHER_PLACE)
    // Requirement 1.5: only the driver's choice asks for permission. Once allowed, it is used from the start.
    navigator.permissions?.query({ name: 'geolocation' })
      .then(status => {
        if (status.state === 'granted') locateWeather()
      })
      .catch(() => undefined)
  }, [loadWeather, locateWeather])

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
    setLoadingCardHeight(phoneCardRef.current?.offsetHeight ?? 0)
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
    // Routes and risk zones cover Gwangju only: rain in another place says nothing about these roads.
    if (!choice.demoMode && weather?.routable === false) return []
    const level = choice.demoMode
      ? rainLevel(choice.rain, choice.alert, config.level_rules)
      : (weather?.available ? weather.level ?? 0 : 0)
    return avoidGroupsFor(level, config.level_rules)
  }, [result, config, choice, weather])

  const alternatives = useMemo(() => result?.alternatives.map(a => a.geometry) ?? [], [result])
  const passedZoneIds = useMemo(() => result?.explanation.passed_zones.map(z => z.id) ?? [], [result])
  const avoidedZoneIds = useMemo(() => result?.explanation.avoided_zones.map(z => z.id) ?? [], [result])
  const checkedAt = zones?.metadata.data_checked_at ?? '-'

  const sceneRain = choice.demoMode ? choice.rain : (weather?.available ? weather.rn1_mm ?? 0 : 0)
  const sceneLevel = levelFor(choice)
  const sceneTime = timeChoice ?? clockTime
  const scene = useMemo(() => weatherScene(sceneRain, sceneLevel, sceneTime), [sceneRain, sceneLevel, sceneTime])
  const mapTheme = mapThemeFor(sceneTime)

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

  // The route screen plans from the original start again, under the rain the drive ended with.
  function endDrive({ routeChanged, demoRain }: DriveExit) {
    setDriveSteps(null)
    if (demoRain) {
      const next = { demoMode: true, rain: demoRain.rn1_mm, alert: demoRain.alert }
      setChoice(next)
      void runRoute(next)
    } else if (routeChanged) {
      void runRoute(choice)
    }
  }

  if (result && driveSteps && config) {
    return <DriveMode result={result} steps={driveSteps} scene={scene} zones={zones} destination={destination}
      levelRules={config.level_rules} onExit={endDrive} />
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
          <MapView key={mapTheme.name} theme={mapTheme} zones={zones} config={config ?? null} highlightGroups={highlightGroups}
            passedZoneIds={passedZoneIds} avoidedZoneIds={avoidedZoneIds} floatingCard={isWide && Boolean(result)}
            route={result?.route.geometry ?? null} baseline={result?.baseline.geometry ?? null}
            alternatives={alternatives} showBaseline={showBaseline} origin={origin} destination={destination} />
        </Suspense>
        {/* The tint stays light: the route and zones underneath must remain readable in any weather. */}
        <div className="map-weather" style={{ backgroundColor: scene.mapOverlay }} aria-hidden="true">
          <WeatherCanvas spec={scene} variant="map" />
        </div>
        {isWide && resultCard && <div className="result-float glass-card">{resultCard}</div>}
      </div>

      <aside ref={asideRef} className="relative min-h-0 flex-1 overflow-y-auto lg:w-[400px] lg:flex-none">
        <div className="space-y-3 p-3 lg:p-0 lg:pr-1">
          {!isWide && resultCard && (
            <div className="glass-card" ref={phoneCardRef}>{resultCard}</div>
          )}
          {!isWide && !resultCard && busy && (
            <div className="glass-card flex items-center justify-center gap-2 text-sm text-muted-foreground"
              style={{ minHeight: loadingCardHeight || undefined }} role="status">
              <Loader2 className="size-4 animate-spin" />경로 계산 중…
            </div>
          )}

          {loadError && (
            <p role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              {loadError}
            </p>
          )}

          <WeatherPanel config={config} weather={weather} loading={weatherLoading} scene={scene} rainShown={sceneRain}
            dummyZonesNotice={dummyNotice(zones, config?.zone_types)} timeChoice={timeChoice} onTimeChoiceChange={setTimeChoice}
            zones={zones} regions={weatherRegions} place={weatherPlace} onPlaceChange={pickWeatherPlace} locating={locating}
            locationNote={locationNote} routeWeather={result?.weather ?? null}
            demoMode={choice.demoMode}
            onDemoModeChange={on => updateChoice({ ...choice, demoMode: on }, true)}
            rain={choice.rain}
            onRainChange={rain => setChoice(c => ({ ...c, rain }))}
            onRainCommit={rain => updateChoice({ ...choice, rain }, true)}
            alert={choice.alert}
            onAlertChange={alert => updateChoice({ ...choice, alert }, true)} />

          <div className="glass-card space-y-3">
            <p className="text-xs leading-5 text-muted-foreground">
              운행 중 비가 강해지면 남은 길을 다시 판단하고, 왜 바꾸는지 설명해요.
            </p>
            <section className="route-fields" aria-label="출발지와 목적지">
              <SearchBar id="origin" label="출발지" value={origin} onChange={pick(setOrigin)} demoPoints={demoPoints}
                bbox={config?.service_area_bbox ?? null} allowCurrentLocation />
              <div className="route-divider">
                <Button type="button" variant="ghost" size="icon-sm" className="route-swap"
                  aria-label="출발·목적지 바꾸기" title="출발·목적지 바꾸기" onClick={swap} disabled={!origin && !destination}>
                  <ArrowUpDown />
                </Button>
              </div>
              <SearchBar id="destination" label="목적지" value={destination} onChange={pick(setDestination)}
                demoPoints={demoPoints} bbox={config?.service_area_bbox ?? null} />
            </section>

            <RoutePanel
              canSubmit={Boolean(origin && destination && strategy)} busy={busy}
              onSubmit={() => {
                scrollToResult.current = true
                void runRoute(choice)
              }} error={routeError} />
          </div>

          <footer className="glass-card space-y-1.5 text-xs leading-5" role="note">
            <p className="text-muted-foreground">
              비가 많이 올수록 지하차도와 침수 이력 도로를 단계적으로 피하는 자동차 경로입니다.
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
