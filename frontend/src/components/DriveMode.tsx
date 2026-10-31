import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { LngLatBounds, MapLibreMap, Marker } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  ArrowUp, ArrowUpLeft, ArrowUpRight, Cloud, CloudDrizzle, CloudLightning, CloudRain, CloudRainWind, CornerUpLeft,
  CornerUpRight, Flag, GitMerge, Loader2, Moon, Navigation, RotateCw, ShieldAlert, ShieldCheck, Sun, Undo2, Volume2,
  VolumeX, X, type LucideIcon,
} from 'lucide-react'

import RerouteCard from '@/components/RerouteCard'
import WeatherCanvas from '@/components/WeatherCanvas'
import { api, errorMessage } from '@/lib/api'
import {
  STEP_LABELS, buildTrack, headingAt, placeSteps, placeZones, pointAt, splitTrack, stepIndexAt, type PlacedStep, type Track,
} from '@/lib/drive'
import { formatDistance, formatDuration, signed } from '@/lib/format'
import { rainLevel } from '@/lib/level'
import { applyKoreanLabels, mapThemeFor, retryStyleOnFailure } from '@/lib/mapTheme'
import '@/lib/mapWorker'
import { avoidCount, avoidIds } from '@/lib/reroute'
import { weatherScene, type SceneKind, type SceneSpec } from '@/lib/scene'
import { speak, speechSupported, stopSpeaking } from '@/lib/speech'
import type {
  GuidanceStep, LevelRules, LineGeometry, LonLat, OsrmRoute, Place, RainState, RerouteResult, RouteResult, StepKind,
  ZoneFeatureCollection,
} from '@/lib/types'


const STEP_ICONS: Record<StepKind, LucideIcon> = {
  depart: Navigation,
  arrive: Flag,
  straight: ArrowUp,
  slight_left: ArrowUpLeft,
  left: CornerUpLeft,
  sharp_left: CornerUpLeft,
  slight_right: ArrowUpRight,
  right: CornerUpRight,
  sharp_right: CornerUpRight,
  uturn: Undo2,
  merge: GitMerge,
  roundabout: RotateCw,
}
const WEATHER_ICONS: Record<SceneKind, LucideIcon> = {
  clear: Sun,
  overcast: Cloud,
  drizzle: CloudDrizzle,
  rain: CloudRain,
  heavy: CloudRainWind,
  downpour: CloudRainWind,
  storm: CloudLightning,
}
// Full scale of the speed ring.
const SPEED_RING_MAX_KPH = 120
const PLAYBACK_RATES = [1, 4, 12]
const DEFAULT_RATE = 4
const FALLBACK_SPEED_KPH = 40
const HUD_UPDATE_MS = 200
const LINE_UPDATE_MS = 500
const CAMERA = { zoom: 16.6, pitch: 62 }
const WARN_AHEAD_M = 1500
const AVOIDED_NEAR_M = 500
// A zone this far from the route's closest point is too far away to call out as "being avoided".
const AVOIDED_MAX_GAP_M = 2500
const BEARING_EASE = 0.12
const NARROW_WIDTH_PX = 760
// Same steps as the demo buttons on the route screen: one per rain level.
const DEMO_RAIN_MM = [0, 35, 55, 75]
const KMA_CHECK_MS = 2 * 60 * 1000
// Too close to the destination for a new route to mean anything.
const MIN_REROUTE_LEFT_M = 300
const NOTICE_MS = 9000
const PREVIEW_MOVE_MS = 800
const SPEAK_RAIN_WORSE = '비가 강해졌어요. 경로를 다시 확인할게요.'

function lineFeature(coordinates: LonLat[]) {
  const geometry: LineGeometry = { type: 'LineString', coordinates }
  return { type: 'Feature' as const, properties: {}, geometry }
}

function setLine(map: MapLibreMap, id: string, coordinates: LonLat[]) {
  const source = map.getSource(id) as unknown as { setData?: (data: unknown) => void } | undefined
  source?.setData?.(lineFeature(coordinates))
}

function arrivalClock(secondsLeft: number) {
  const at = new Date(Date.now() + secondsLeft * 1000)
  return at.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })
}

function speedAt(steps: PlacedStep[], distance: number, fallback: number) {
  if (steps.length === 0) return fallback
  return steps[stepIndexAt(steps, distance)].speedKph || fallback
}

// What the car is following. Replaced as a whole, so the map loop never sees a mix of two routes.
interface Nav {
  track: Track
  placedSteps: PlacedStep[]
  averageKph: number
  duration: number
  passedIds: string[]
  avoidedIds: string[]
  failed: boolean
}

function makeNav(route: OsrmRoute, steps: GuidanceStep[], passedIds: string[], avoidedIds: string[], failed: boolean): Nav {
  const track = buildTrack(route.geometry.coordinates)
  return {
    track,
    placedSteps: placeSteps(steps, track),
    averageKph: route.duration > 0 ? (track.length / route.duration) * 3.6 : FALLBACK_SPEED_KPH,
    duration: route.duration,
    passedIds,
    avoidedIds,
    failed,
  }
}

type Reroute =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'request'; decision: RerouteResult; steps: GuidanceStep[]; previous: RainState }

interface Notice {
  tone: 'safe' | 'warn' | 'danger'
  text: string
}

// A warning that holds while the zones it names are still ahead.
interface StandingWarning {
  tone: 'warn' | 'danger'
  label: string
  ids: string[]
}

// What the route screen needs to catch up with the drive.
export interface DriveExit {
  routeChanged: boolean
  demoRain: RainState | null
}

interface Preview {
  current: LonLat[]
  candidate: LonLat[]
}

function vehicleElement() {
  const element = document.createElement('div')
  element.className = 'drive-vehicle'
  element.innerHTML = '<svg viewBox="0 0 48 48" width="52" height="52" aria-hidden="true"><path d="M24 4 41 42 24 33 7 42Z" fill="#2563eb" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/></svg>'
  return element
}

interface Props {
  result: RouteResult
  steps: GuidanceStep[]
  scene: SceneSpec
  zones: ZoneFeatureCollection | null
  destination: Place | null
  levelRules: LevelRules
  onExit: (summary: DriveExit) => void
}

export default function DriveMode({ result, steps, scene, zones, destination, levelRules, onExit }: Props) {
  const [nav, setNav] = useState(() => makeNav(result.route, steps, result.explanation.passed_zones.map(z => z.id),
    result.explanation.avoided_zones.map(z => z.id), result.explanation.status === 'avoid_failed'))
  const { track, placedSteps, averageKph } = nav
  const passed = useMemo(() => placeZones(zones, nav.passedIds, track), [zones, nav, track])
  const avoided = useMemo(() => placeZones(zones, nav.avoidedIds, track)
    .filter(zone => zone.gap < AVOIDED_MAX_GAP_M), [zones, nav, track])

  // Chosen when the drive starts: swapping styles mid-drive would drop the route layers.
  const [theme] = useState(() => mapThemeFor(scene.time))
  const container = useRef<HTMLDivElement>(null)
  const atRef = useRef(0)
  const rateRef = useRef(DEFAULT_RATE)
  const navRef = useRef(nav)
  // Road already driven on earlier routes, so the line behind the car survives a route change.
  const travelledRef = useRef<LonLat[]>([])
  const pausedRef = useRef(false)
  const previewRef = useRef<Preview | null>(null)
  const cardRef = useRef<HTMLElement>(null)
  const turnRef = useRef<HTMLElement>(null)
  const controlsRef = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState(0)
  const [rate, setRate] = useState(DEFAULT_RATE)
  const [mapError, setMapError] = useState(false)

  const [rain, setRain] = useState<RainState>({ rn1_mm: result.weather.rn1_mm, alert: result.weather.alert })
  const rainRef = useRef(rain)
  // The rain the route was last settled against, and the level of the latest check.
  const settledRainRef = useRef(rain)
  const checkedLevelRef = useRef(result.weather.level)
  const demoRainRef = useRef(result.weather.source === 'demo')
  const [demoRain, setDemoRain] = useState(result.weather.source === 'demo')
  const abortRef = useRef<AbortController | null>(null)
  const [reroute, setReroute] = useState<Reroute>({ kind: 'idle' })
  const [notice, setNotice] = useState<Notice | null>(null)
  const [standing, setStanding] = useState<StandingWarning | null>(null)
  const [voiceOn, setVoiceOn] = useState(true)
  const voiceRef = useRef(true)

  const level = rainLevel(rain.rn1_mm, rain.alert, levelRules)
  const driveScene = useMemo(() => weatherScene(rain.rn1_mm, level, scene.time), [rain, level, scene.time])

  useEffect(() => {
    rateRef.current = rate
  }, [rate])

  const say = useCallback((text: string, interrupt = false) => {
    if (voiceRef.current) speak(text, { interrupt })
  }, [])

  function toggleVoice() {
    voiceRef.current = !voiceRef.current
    setVoiceOn(voiceRef.current)
    if (!voiceRef.current) stopSpeaking()
  }

  const settle = useCallback((settled: RainState, message: Notice | null, warning: StandingWarning | null = null) => {
    settledRainRef.current = settled
    pausedRef.current = false
    previewRef.current = null
    setReroute({ kind: 'idle' })
    setNotice(message)
    setStanding(warning)
  }, [])

  const checkRoute = useCallback(async (next: RainState, useDemoValue: boolean) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const previous = settledRainRef.current
    const { track: current, duration } = navRef.current
    const distance = atRef.current
    const position = pointAt(current, distance)
    const { left: remaining } = splitTrack(current, distance)
    // The car waits while the route is checked, so the answer still starts where the car is.
    pausedRef.current = true
    previewRef.current = null
    setNotice(null)
    setStanding(null)
    setReroute({ kind: 'checking' })
    say(SPEAK_RAIN_WORSE, true)
    try {
      const destinationPoint = current.coordinates[current.coordinates.length - 1]
      const decision = await api.reroute({
        position: { lon: position[0], lat: position[1] },
        destination: { lon: destinationPoint[0], lat: destinationPoint[1] },
        heading: headingAt(current, distance),
        remaining,
        remaining_duration_s: current.length > 0 ? duration * ((current.length - distance) / current.length) : 0,
        previous,
        weather_override: useDemoValue ? next : null,
      }, controller.signal)
      if (decision.action === 'recommend') {
        // Guidance is an extra on top of the route: the change still works with the route line alone.
        const guidance = await api.guidance(decision.route.geometry.coordinates).catch(() => ({ steps: [] }))
        if (controller.signal.aborted) return
        previewRef.current = { current: remaining, candidate: decision.route.geometry.coordinates }
        setReroute({ kind: 'request', decision, steps: guidance.steps, previous })
        return
      }
      if (controller.signal.aborted) return
      if (decision.action === 'keep') {
        settle(next, { tone: 'safe', text: '남은 경로에 이번 단계에서 피할 구간이 없어요' })
      } else {
        settle(next, null, { tone: 'danger', label: '더 나은 경로를 찾지 못했어요', ids: avoidIds(decision) })
      }
      say(decision.text)
    } catch (e) {
      if (controller.signal.aborted) return
      // Back to the last settled level, so the next check or button press tries again.
      checkedLevelRef.current = rainLevel(previous.rn1_mm, previous.alert, levelRules)
      settle(previous, { tone: 'warn', text: `${errorMessage(e, '경로를 확인하지 못했어요')} · 지금 경로로 안내해요` })
      say('경로를 확인하지 못했어요. 지금 경로로 안내해요.')
    }
  }, [levelRules, say, settle])

  const applyRain = useCallback((next: RainState, useDemoValue: boolean) => {
    const nextLevel = rainLevel(next.rn1_mm, next.alert, levelRules)
    rainRef.current = next
    setRain(next)
    const { track: current } = navRef.current
    if (current.length - atRef.current < MIN_REROUTE_LEFT_M) {
      checkedLevelRef.current = nextLevel
      return
    }
    if (nextLevel > checkedLevelRef.current) {
      checkedLevelRef.current = nextLevel
      void checkRoute(next, useDemoValue)
    } else if (nextLevel < checkedLevelRef.current) {
      // The rain eased: a question about the heavier rain no longer applies.
      checkedLevelRef.current = nextLevel
      abortRef.current?.abort()
      stopSpeaking()
      settle(next, null)
    }
  }, [checkRoute, levelRules, settle])

  function pickDemoRain(mm: number) {
    demoRainRef.current = true
    setDemoRain(true)
    applyRain({ rn1_mm: mm, alert: 'none' }, true)
  }

  // Real rain is re-read at the car while driving, unless the demo buttons took over.
  const followsKma = result.weather.source === 'kma'
  useEffect(() => {
    if (!followsKma) return
    const timer = window.setInterval(() => {
      if (demoRainRef.current) return
      const [lon, lat] = pointAt(navRef.current.track, atRef.current)
      api.weatherAt({ lon, lat }).then(data => {
        if (demoRainRef.current || !data.available || data.rn1_mm === null) return
        applyRain({ rn1_mm: data.rn1_mm, alert: data.alert_status === 'ok' ? data.alert : 'none' }, false)
      }).catch(() => undefined) // the next check tries again
    }, KMA_CHECK_MS)
    return () => window.clearInterval(timer)
  }, [followsKma, applyRain])

  useEffect(() => () => {
    abortRef.current?.abort()
    stopSpeaking()
  }, [])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), NOTICE_MS)
    return () => window.clearTimeout(timer)
  }, [notice])

  function acceptReroute() {
    if (reroute.kind !== 'request') return
    const { decision } = reroute
    const old = navRef.current
    travelledRef.current = [...travelledRef.current, ...splitTrack(old.track, atRef.current).done]
    const next = makeNav(decision.route, reroute.steps, decision.candidate.zones.map(z => z.id),
      decision.avoided_zone_ids, decision.candidate.hard_zone_ids.length > 0)
    navRef.current = next
    atRef.current = 0
    setAt(0)
    setNav(next)
    const added = decision.candidate.duration_s - decision.current.duration_s
    settle(rainRef.current, { tone: 'safe', text: `경로를 변경했어요 · 남은 시간 ${signed(added, formatDuration)}` })
    // Queued: three seconds is shorter than the summary, which should still finish.
    say('새 경로로 안내할게요.')
  }

  function declineReroute() {
    if (reroute.kind !== 'request') return
    const count = avoidCount(reroute.decision)
    settle(rainRef.current, null, { tone: 'warn', label: '지금 경로를 유지 중이에요', ids: avoidIds(reroute.decision) })
    say(`지금 경로를 유지해요. 남은 길에 피할 구간 ${count}곳이 있어요.`, true)
  }

  const speakExplanation = useCallback((text: string) => say(text), [say])

  function finish() {
    const start = result.weather
    const rainChanged = rainRef.current.rn1_mm !== start.rn1_mm || rainRef.current.alert !== start.alert
    onExit({ routeChanged: travelledRef.current.length > 0, demoRain: demoRainRef.current && rainChanged ? rainRef.current : null })
  }

  useEffect(() => {
    if (!container.current) return
    const first = navRef.current
    const map = new MapLibreMap({
      container: container.current, style: theme.styleUrl, zoom: CAMERA.zoom, pitch: CAMERA.pitch,
      center: first.track.coordinates[0], interactive: false, attributionControl: { compact: true },
    })
    const marker = new Marker({ element: vehicleElement(), rotationAlignment: 'map', pitchAlignment: 'map' })
      .setLngLat(first.track.coordinates[0]).addTo(map)
    let frame = 0
    let last = performance.now()
    let lastHud = 0
    let lastLine = 0
    let heading = headingAt(first.track, 0)
    let ready = false
    let moving = false
    let shownTrack = first.track
    let shownPreview: Preview | null = null
    let cameraBusyUntil = 0
    let padding: ReturnType<typeof followPadding> | null = null
    let lastPadding = 0

    retryStyleOnFailure(map, theme.styleUrl, () => {
      setMapError(true)
      moving = true // keep the guidance running even without a base map
    })
    // Not 'load': that waits for every tile, which a moving camera can delay for a long time.
    map.on('style.load', () => {
      applyKoreanLabels(map)
      for (const id of ['drive-done', 'drive-left']) map.addSource(id, { type: 'geojson', data: lineFeature(first.track.coordinates) })
      map.addSource('drive-preview', { type: 'geojson', data: lineFeature([]) })
      const zoneData = zones ?? { type: 'FeatureCollection', features: [] }
      map.addSource('drive-zones', { type: 'geojson', data: zoneData as never })
      map.addLayer({ id: 'drive-zones-fill', type: 'fill', source: 'drive-zones', paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.28 } })
      map.addLayer({ id: 'drive-zones-line', type: 'line', source: 'drive-zones', paint: { 'line-color': '#fbbf24', 'line-width': 1.5, 'line-opacity': 0.8 } })
      const line = { 'line-cap': 'round', 'line-join': 'round' } as const
      map.addLayer({ id: 'drive-done', type: 'line', source: 'drive-done', layout: line, paint: { 'line-color': theme.travelled, 'line-width': 9, 'line-opacity': 0.5 } })
      map.addLayer({ id: 'drive-left-glow', type: 'line', source: 'drive-left', layout: line, paint: { 'line-color': '#2dd4bf', 'line-width': 22, 'line-blur': 12, 'line-opacity': 0.55 } })
      map.addLayer({ id: 'drive-left-casing', type: 'line', source: 'drive-left', layout: line, paint: { 'line-color': theme.name === 'light' ? '#0f766e' : '#042f2e', 'line-width': 13 } })
      map.addLayer({ id: 'drive-left', type: 'line', source: 'drive-left', layout: line, paint: { 'line-color': '#2dd4bf', 'line-width': 9 } })
      map.addLayer({ id: 'drive-preview-casing', type: 'line', source: 'drive-preview', layout: line, paint: { 'line-color': theme.name === 'light' ? '#0f766e' : '#042f2e', 'line-width': 12 } })
      map.addLayer({ id: 'drive-preview', type: 'line', source: 'drive-preview', layout: line, paint: { 'line-color': '#2dd4bf', 'line-width': 8 } })
      // 3D buildings when the style's vector source has them; the map still works without.
      // Some styles already have their own.
      const hasBuildings = map.getStyle().layers.some(layer => layer.type === 'fill-extrusion')
      if (!hasBuildings && map.getSource('openmaptiles')) {
        map.addLayer({
          id: 'drive-buildings', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 15,
          paint: {
            'fill-extrusion-color': theme.buildings,
            'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8],
            'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
            'fill-extrusion-opacity': 0.82,
          },
        }, 'drive-done')
      }
      ready = true
      moving = true
    })

    function followPadding(width: number, height: number) {
      if (width >= NARROW_WIDTH_PX) return { top: height * 0.42, bottom: 0, left: 0, right: 0 }
      // Phones: the car sits in the gap between the turn card and the controls, whatever their height.
      const turn = turnRef.current?.getBoundingClientRect()
      const controls = controlsRef.current?.getBoundingClientRect()
      if (!turn?.height || !controls?.height) return { top: height * 0.22, bottom: 0, left: 0, right: 0 }
      return { top: turn.bottom, bottom: Math.max(height - controls.top, 0), left: 0, right: 0 }
    }

    // While the driver is asked, the map shows both routes from above with the current one in amber.
    function showPreview(preview: Preview | null, position: LonLat, width: number, height: number, now: number) {
      shownPreview = preview
      setLine(map, 'drive-preview', preview?.candidate ?? [])
      map.setPaintProperty('drive-left', 'line-color', preview ? '#f59e0b' : '#2dd4bf')
      map.setPaintProperty('drive-left-glow', 'line-opacity', preview ? 0 : 0.55)
      map.stop()
      cameraBusyUntil = now + PREVIEW_MOVE_MS
      if (!preview) {
        map.easeTo({ center: position, bearing: heading, zoom: CAMERA.zoom, pitch: CAMERA.pitch,
          padding: followPadding(width, height), duration: PREVIEW_MOVE_MS })
        return
      }
      const bounds = new LngLatBounds()
      for (const point of [...preview.current, ...preview.candidate]) bounds.extend(point)
      const card = cardRef.current?.getBoundingClientRect()
      const narrow = width < NARROW_WIDTH_PX
      map.jumpTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 } })
      map.fitBounds(bounds, {
        padding: {
          top: narrow ? 24 : 70,
          bottom: narrow ? height - (card?.top ?? height * 0.5) + 24 : 130,
          left: narrow ? 44 : (card?.right ?? 0) + 40,
          right: narrow ? 44 : 70,
        },
        bearing: 0, pitch: 0, duration: PREVIEW_MOVE_MS,
      })
    }

    function tick(now: number) {
      frame = requestAnimationFrame(tick)
      // Clamped so a backgrounded tab does not jump ahead, but loose enough for slow devices to keep pace.
      const elapsed = Math.min((now - last) / 1000, 0.25)
      last = now
      const { track: live, placedSteps: liveSteps, averageKph: liveKph } = navRef.current
      if (live !== shownTrack) {
        shownTrack = live
        lastLine = 0
      }
      const kph = speedAt(liveSteps, atRef.current, liveKph)
      if (moving && !pausedRef.current && now >= cameraBusyUntil) {
        atRef.current = Math.min(atRef.current + (kph / 3.6) * rateRef.current * elapsed, live.length)
      }
      const position = pointAt(live, atRef.current)
      const target = headingAt(live, atRef.current)
      heading += ((((target - heading) % 360) + 540) % 360 - 180) * BEARING_EASE
      marker.setLngLat(position).setRotation(heading)
      const height = container.current?.clientHeight ?? 800
      const width = container.current?.clientWidth ?? 1200
      if (ready && previewRef.current !== shownPreview) showPreview(previewRef.current, position, width, height, now)
      if (!shownPreview && now >= cameraBusyUntil) {
        if (!padding || now - lastPadding > LINE_UPDATE_MS) {
          padding = followPadding(width, height)
          lastPadding = now
        }
        map.jumpTo({ center: position, bearing: heading, padding })
      }
      if (ready && now - lastLine > LINE_UPDATE_MS) {
        lastLine = now
        const { done, left } = splitTrack(live, atRef.current)
        setLine(map, 'drive-done', [...travelledRef.current, ...done])
        setLine(map, 'drive-left', left)
      }
      if (now - lastHud > HUD_UPDATE_MS) {
        lastHud = now
        setAt(atRef.current)
      }
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
      marker.remove()
      map.remove()
    }
    // The map lives for one drive. The route and playback rate go through refs so changing them keeps the map.
  }, [zones, theme])

  const arrived = at >= track.length - 1
  const waiting = reroute.kind !== 'idle'
  const speed = arrived || waiting ? 0 : Math.round(speedAt(placedSteps, at, averageKph))
  const left = Math.max(track.length - at, 0)
  const timeLeft = nav.duration * (track.length > 0 ? left / track.length : 0)
  const stepIndex = placedSteps.length ? stepIndexAt(placedSteps, at) : -1
  const current = stepIndex >= 0 ? placedSteps[stepIndex] : null
  const next = stepIndex >= 0 ? placedSteps[stepIndex + 1] ?? null : null
  const afterNext = stepIndex >= 0 ? placedSteps[stepIndex + 2] ?? null : null
  const nextKind: StepKind = next?.kind ?? (current ? 'arrive' : 'straight')
  const TurnIcon = STEP_ICONS[nextKind]
  const WeatherIcon = driveScene.kind === 'clear' && driveScene.time === 'night' ? Moon : WEATHER_ICONS[driveScene.kind]
  const toNext = next ? Math.max(next.start - at, 0) : left
  const roadAhead = nextKind === 'arrive' ? destination?.name ?? '' : next?.name ?? ''

  const warning = passed.filter(z => z.at >= at && z.at - at <= WARN_AHEAD_M).sort((a, b) => a.at - b.at)[0]
  const avoiding = arrived ? undefined : avoided.find(z => Math.abs(z.at - at) <= AVOIDED_NEAR_M)
  const failed = nav.failed
  const standingAhead = standing ? placeZones(zones, standing.ids, track).filter(z => z.at >= at).length : 0

  return (
    <div className="drive-shell" data-testid="drive-mode" data-arrived={arrived} data-map-theme={theme.name} data-reroute={reroute.kind}>
      {/* A wrapper holds the size: maplibre's own CSS sets its container to position: relative. */}
      <div className="absolute inset-0">
        <div ref={container} className="h-full w-full" role="region" aria-label="운행 지도" />
      </div>
      <div className="map-weather" style={{ backgroundColor: driveScene.mapOverlay }} aria-hidden="true">
        <WeatherCanvas spec={driveScene} variant="map" />
      </div>
      <div className="drive-vignette" aria-hidden="true" />

      <section ref={turnRef} className="drive-turn drive-glass" aria-label="다음 안내" aria-live="polite">
        <div className="drive-turn-main">
          <span className="drive-turn-icon"><TurnIcon strokeWidth={2.4} /></span>
          <div className="min-w-0">
            <p className="drive-turn-distance">{formatDistance(toNext)}</p>
            <p className="drive-turn-label">{STEP_LABELS[nextKind]}</p>
          </div>
        </div>
        {roadAhead && <p className="drive-turn-road" title={roadAhead}>{roadAhead}</p>}
        {afterNext && (
          <p className="drive-turn-then">그다음 {formatDistance(afterNext.start - (next?.start ?? 0))} 뒤 {STEP_LABELS[afterNext.kind]}</p>
        )}
        {placedSteps.length === 0 && <p className="drive-turn-then">회전 안내를 받지 못해 경로선만 표시합니다.</p>}
      </section>

      <div ref={controlsRef} className="drive-top-right">
        <div className="drive-top-row">
          <span className="drive-chip drive-glass"><WeatherIcon />{driveScene.title} · 강수 {level}단계</span>
          {speechSupported() && (
            <button type="button" className="drive-voice drive-glass" aria-pressed={voiceOn} onClick={toggleVoice}
              aria-label={voiceOn ? '음성 안내 끄기' : '음성 안내 켜기'} title={voiceOn ? '음성 안내 끄기' : '음성 안내 켜기'}>
              {voiceOn ? <Volume2 /> : <VolumeX />}
            </button>
          )}
        </div>
        <div className="drive-rate drive-glass" role="group" aria-label="시연 주행 배속">
          <span>시연 주행</span>
          {PLAYBACK_RATES.map(value => (
            <button key={value} type="button" aria-pressed={rate === value} onClick={() => setRate(value)}>×{value}</button>
          ))}
        </div>
        <div className="drive-rate drive-glass" role="group" aria-label="시연 강수량">
          <span>시연 강수</span>
          {DEMO_RAIN_MM.map(mm => (
            <button key={mm} type="button" disabled={arrived} aria-pressed={demoRain && rain.rn1_mm === mm}
              onClick={() => pickDemoRain(mm)}>{mm}</button>
          ))}
        </div>
      </div>

      <div className="drive-alerts">
        {reroute.kind === 'checking' && (
          <p role="status" className="drive-alert drive-alert-warn">
            <Loader2 className="animate-spin" />비가 강해졌어요 · 경로를 다시 확인하는 중
          </p>
        )}
        {notice && (
          <p role="status" className={`drive-alert drive-alert-${notice.tone}`} data-testid="drive-notice">
            {notice.tone === 'safe' ? <ShieldCheck /> : <ShieldAlert />}{notice.text}
          </p>
        )}
        {standing && standingAhead > 0 && (
          <p role="status" className={`drive-alert drive-alert-${standing.tone}`} data-testid="drive-standing">
            <ShieldAlert />{standing.label} · 앞에 피할 구간 {standingAhead}곳
          </p>
        )}
        {failed && (
          <p role="alert" className="drive-alert drive-alert-danger">
            <ShieldAlert />피할 구역을 모두 피하지 못한 경로입니다. 안전한 경로가 아닙니다.
          </p>
        )}
        {warning && (
          <p role="alert" className="drive-alert drive-alert-warn">
            <ShieldAlert />{formatDistance(warning.at - at)} 앞 {warning.name}
          </p>
        )}
        {!warning && avoiding && (
          <p className="drive-alert drive-alert-safe"><ShieldCheck />{avoiding.name} 우회 중</p>
        )}
      </div>

      <div className="drive-speed" aria-label={`시연 속도 시속 ${speed}킬로미터`}
        style={{ '--speed-share': Math.min((speed / SPEED_RING_MAX_KPH) * 100, 100) } as CSSProperties}>
        <strong>{speed}</strong>
        <span>km/h</span>
      </div>

      <section className="drive-dock drive-glass" aria-label="도착 정보">
        <div className="drive-progress" aria-hidden="true"><span style={{ width: `${track.length ? (at / track.length) * 100 : 0}%` }} /></div>
        <div className="drive-dock-road">{current?.name || ' '}</div>
        <dl className="drive-stats">
          <div><dt>도착 예정</dt><dd>{arrivalClock(timeLeft)}</dd></div>
          <div><dt>남은 시간</dt><dd>{formatDuration(timeLeft)}</dd></div>
          <div><dt>남은 거리</dt><dd>{formatDistance(left)}</dd></div>
        </dl>
        <button type="button" className="drive-exit" onClick={finish}><X />안내 종료</button>
      </section>

      <p className="drive-note">
        시연 주행 · 실제 위치, 도로 통제, 침수 여부는 확인하지 않습니다{mapError ? ' · 지도를 불러오지 못했습니다' : ''}
      </p>

      {reroute.kind === 'request' && (
        <RerouteCard key={reroute.decision.weather.level} decision={reroute.decision} previous={reroute.previous} cardRef={cardRef}
          onSpeak={speakExplanation} onAccept={acceptReroute} onDecline={declineReroute} />
      )}

      {arrived && (
        <div className="drive-arrived" role="status">
          <div className="drive-glass">
            <span className="drive-arrived-icon"><Flag /></span>
            <h2>목적지에 도착했습니다</h2>
            <p>{destination?.name}</p>
            <button type="button" className="drive-exit" onClick={finish}>경로 화면으로 돌아가기</button>
          </div>
        </div>
      )}
    </div>
  )
}
