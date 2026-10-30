import { useEffect, useMemo, useRef, useState } from 'react'
import { MapLibreMap, Marker } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  ArrowUp, ArrowUpLeft, ArrowUpRight, CornerUpLeft, CornerUpRight, Flag, GitMerge, Navigation, RotateCw,
  ShieldAlert, ShieldCheck, Undo2, X, type LucideIcon,
} from 'lucide-react'

import WeatherCanvas from '@/components/WeatherCanvas'
import { Button } from '@/components/ui/button'
import {
  STEP_LABELS, buildTrack, headingAt, placeSteps, placeZones, pointAt, splitTrack, stepIndexAt, type PlacedStep,
} from '@/lib/drive'
import { formatDistance, formatDuration } from '@/lib/format'
import '@/lib/mapWorker'
import type { SceneSpec } from '@/lib/scene'
import type { GuidanceStep, LineGeometry, LonLat, Place, RouteResult, StepKind, ZoneFeatureCollection } from '@/lib/types'

const STYLE_URL = 'https://tiles.openfreemap.org/styles/fiord'

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

function vehicleElement() {
  const element = document.createElement('div')
  element.className = 'drive-vehicle'
  element.innerHTML = '<svg viewBox="0 0 48 48" width="52" height="52" aria-hidden="true"><path d="M24 4 41 42 24 33 7 42Z" fill="#f4ecd8" stroke="#0b1320" stroke-width="2.5" stroke-linejoin="round"/></svg>'
  return element
}

interface Props {
  result: RouteResult
  steps: GuidanceStep[]
  scene: SceneSpec
  zones: ZoneFeatureCollection | null
  destination: Place | null
  onExit: () => void
}

export default function DriveMode({ result, steps, scene, zones, destination, onExit }: Props) {
  const track = useMemo(() => buildTrack(result.route.geometry.coordinates), [result])
  const placedSteps = useMemo(() => placeSteps(steps, track), [steps, track])
  const passed = useMemo(() => placeZones(zones, result.explanation.passed_zones.map(z => z.id), track), [zones, result, track])
  const avoided = useMemo(() => placeZones(zones, result.explanation.avoided_zones.map(z => z.id), track)
    .filter(zone => zone.gap < AVOIDED_MAX_GAP_M), [zones, result, track])
  const averageKph = result.route.duration > 0 ? (track.length / result.route.duration) * 3.6 : FALLBACK_SPEED_KPH

  const container = useRef<HTMLDivElement>(null)
  const atRef = useRef(0)
  const rateRef = useRef(DEFAULT_RATE)
  const [at, setAt] = useState(0)
  const [rate, setRate] = useState(DEFAULT_RATE)
  const [mapError, setMapError] = useState(false)

  useEffect(() => {
    rateRef.current = rate
  }, [rate])

  useEffect(() => {
    if (!container.current) return
    const map = new MapLibreMap({
      container: container.current, style: STYLE_URL, zoom: CAMERA.zoom, pitch: CAMERA.pitch,
      center: track.coordinates[0], interactive: false, attributionControl: { compact: true },
    })
    const marker = new Marker({ element: vehicleElement(), rotationAlignment: 'map', pitchAlignment: 'map' })
      .setLngLat(track.coordinates[0]).addTo(map)
    let frame = 0
    let last = performance.now()
    let lastHud = 0
    let lastLine = 0
    let heading = headingAt(track, 0)
    let ready = false
    let moving = false

    map.on('error', () => {
      if (map.isStyleLoaded()) return
      setMapError(true)
      moving = true // keep the guidance running even without a base map
    })
    // Not 'load': that waits for every tile, which a moving camera can delay for a long time.
    map.on('style.load', () => {
      for (const id of ['drive-done', 'drive-left']) map.addSource(id, { type: 'geojson', data: lineFeature(track.coordinates) })
      const zoneData = zones ?? { type: 'FeatureCollection', features: [] }
      map.addSource('drive-zones', { type: 'geojson', data: zoneData as never })
      map.addLayer({ id: 'drive-zones-fill', type: 'fill', source: 'drive-zones', paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.28 } })
      map.addLayer({ id: 'drive-zones-line', type: 'line', source: 'drive-zones', paint: { 'line-color': '#fbbf24', 'line-width': 1.5, 'line-opacity': 0.8 } })
      const line = { 'line-cap': 'round', 'line-join': 'round' } as const
      map.addLayer({ id: 'drive-done', type: 'line', source: 'drive-done', layout: line, paint: { 'line-color': '#94a3b8', 'line-width': 9, 'line-opacity': 0.4 } })
      map.addLayer({ id: 'drive-left-glow', type: 'line', source: 'drive-left', layout: line, paint: { 'line-color': '#34d399', 'line-width': 20, 'line-blur': 12, 'line-opacity': 0.5 } })
      map.addLayer({ id: 'drive-left-casing', type: 'line', source: 'drive-left', layout: line, paint: { 'line-color': '#022c22', 'line-width': 13 } })
      map.addLayer({ id: 'drive-left', type: 'line', source: 'drive-left', layout: line, paint: { 'line-color': '#34d399', 'line-width': 9 } })
      // 3D buildings when the style's vector source has them; the map still works without.
      if (map.getSource('openmaptiles')) {
        map.addLayer({
          id: 'drive-buildings', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 15,
          paint: {
            'fill-extrusion-color': '#2b3650',
            'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8],
            'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
            'fill-extrusion-opacity': 0.82,
          },
        }, 'drive-done')
      }
      ready = true
      moving = true
    })

    function tick(now: number) {
      frame = requestAnimationFrame(tick)
      // Clamped so a backgrounded tab does not jump ahead, but loose enough for slow devices to keep pace.
      const elapsed = Math.min((now - last) / 1000, 0.25)
      last = now
      const kph = speedAt(placedSteps, atRef.current, averageKph)
      if (moving) atRef.current = Math.min(atRef.current + (kph / 3.6) * rateRef.current * elapsed, track.length)
      const position = pointAt(track, atRef.current)
      const target = headingAt(track, atRef.current)
      heading += ((((target - heading) % 360) + 540) % 360 - 180) * BEARING_EASE
      marker.setLngLat(position).setRotation(heading)
      const height = container.current?.clientHeight ?? 800
      const width = container.current?.clientWidth ?? 1200
      const topShare = width < NARROW_WIDTH_PX ? 0.22 : 0.42 // phones keep the car clear of the lower controls
      map.jumpTo({ center: position, bearing: heading, padding: { top: height * topShare, bottom: 0, left: 0, right: 0 } })
      if (ready && now - lastLine > LINE_UPDATE_MS) {
        lastLine = now
        const { done, left } = splitTrack(track, atRef.current)
        setLine(map, 'drive-done', done)
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
    // The map lives for one drive. The playback rate goes through a ref so changing it keeps the map.
  }, [track, placedSteps, averageKph, zones])

  const arrived = at >= track.length - 1
  const speed = arrived ? 0 : Math.round(speedAt(placedSteps, at, averageKph))
  const left = Math.max(track.length - at, 0)
  const timeLeft = result.route.duration * (track.length > 0 ? left / track.length : 0)
  const stepIndex = placedSteps.length ? stepIndexAt(placedSteps, at) : -1
  const current = stepIndex >= 0 ? placedSteps[stepIndex] : null
  const next = stepIndex >= 0 ? placedSteps[stepIndex + 1] ?? null : null
  const afterNext = stepIndex >= 0 ? placedSteps[stepIndex + 2] ?? null : null
  const nextKind: StepKind = next?.kind ?? (current ? 'arrive' : 'straight')
  const TurnIcon = STEP_ICONS[nextKind]
  const toNext = next ? Math.max(next.start - at, 0) : left
  const roadAhead = nextKind === 'arrive' ? destination?.name ?? '' : next?.name ?? ''

  const warning = passed.filter(z => z.at >= at && z.at - at <= WARN_AHEAD_M).sort((a, b) => a.at - b.at)[0]
  const avoiding = avoided.find(z => Math.abs(z.at - at) <= AVOIDED_NEAR_M)
  const failed = result.explanation.status === 'avoid_failed'

  return (
    <div className="drive-shell dark" data-testid="drive-mode" data-arrived={arrived}>
      {/* A wrapper holds the size: maplibre's own CSS sets its container to position: relative. */}
      <div className="absolute inset-0">
        <div ref={container} className="h-full w-full" role="region" aria-label="운행 지도" />
      </div>
      <div className="map-weather" style={{ backgroundColor: `rgb(6 10 20 / ${scene.mapTint})` }} aria-hidden="true">
        <WeatherCanvas spec={scene} variant="map" />
      </div>
      <div className="drive-vignette" aria-hidden="true" />

      <section className="drive-turn drive-glass" aria-label="다음 안내" aria-live="polite">
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

      <div className="drive-top-right">
        <span className="drive-chip drive-glass">{scene.title} · 강수 {result.weather.level}단계</span>
        <div className="drive-rate drive-glass" role="group" aria-label="시연 주행 배속">
          <span>시연 주행</span>
          {PLAYBACK_RATES.map(value => (
            <button key={value} type="button" aria-pressed={rate === value} onClick={() => setRate(value)}>×{value}</button>
          ))}
        </div>
      </div>

      <div className="drive-alerts">
        {failed && (
          <p role="alert" className="drive-alert drive-alert-danger">
            <ShieldAlert />위험 구역을 피하지 못한 경로입니다. 안전한 경로가 아닙니다.
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

      <div className="drive-speed drive-glass" aria-label={`시연 속도 시속 ${speed}킬로미터`}>
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
        <Button type="button" variant="secondary" className="drive-exit" onClick={onExit}><X />안내 종료</Button>
      </section>

      <p className="drive-note">
        시연 주행 · 실제 위치, 도로 통제, 침수 여부는 확인하지 않습니다{mapError ? ' · 지도를 불러오지 못했습니다' : ''}
      </p>

      {arrived && (
        <div className="drive-arrived" role="status">
          <div className="drive-glass">
            <Flag />
            <h2>목적지에 도착했습니다</h2>
            <p>{destination?.name}</p>
            <Button type="button" onClick={onExit}>경로 화면으로 돌아가기</Button>
          </div>
        </div>
      )}
    </div>
  )
}
