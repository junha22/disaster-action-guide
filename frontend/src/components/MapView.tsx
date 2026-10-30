import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, MapLibreMap, Marker, NavigationControl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

import '@/lib/mapWorker'

import RiskLayer from '@/components/RiskLayer'
import type { AppConfig, LineGeometry, LonLat, Place, ZoneFeatureCollection, ZoneType } from '@/lib/types'

// OpenFreeMap: no API key. The default attribution control stays on (requirement 6.1).
const STYLE_URL = 'https://tiles.openfreemap.org/styles/fiord'
const GWANGJU: LonLat = [126.85, 35.16]

const LINES = [
  { id: 'route-alternatives', color: '#c4b5fd', width: 3, dash: undefined as number[] | undefined, opacity: 0.7 },
  { id: 'route-baseline', color: '#e2e8f0', width: 3.5, dash: [0.5, 2], opacity: 0.9 },
  { id: 'route-main', color: '#34d399', width: 6, dash: undefined, opacity: 1 },
]
// Keeps the route readable over bright roads and the rain overlay.
const ROUTE_CASING = { id: 'route-main-casing', color: '#022c22', width: 10 }
const CARD_SPACE_PX = 390

interface Props {
  zones: ZoneFeatureCollection | null
  zoneTypes: AppConfig['zone_types'] | null
  highlightTypes: ZoneType[]
  passedZoneIds: string[]
  // True when a result card covers the left side of the map.
  floatingCard: boolean
  route: LineGeometry | null
  baseline: LineGeometry | null
  alternatives: LineGeometry[]
  showBaseline: boolean
  origin: Place | null
  destination: Place | null
}

function collection(lines: LineGeometry[]) {
  return {
    type: 'FeatureCollection' as const,
    features: lines.map(geometry => ({ type: 'Feature' as const, properties: {}, geometry })),
  }
}

function setLines(map: MapLibreMap, id: string, lines: LineGeometry[]) {
  const source = map.getSource(id)
  if (source && 'setData' in source) (source as { setData: (d: unknown) => void }).setData(collection(lines))
}

export default function MapView(props: Props) {
  const { zones, zoneTypes, highlightTypes, passedZoneIds, floatingCard, route, baseline, alternatives, showBaseline,
    origin, destination } = props
  const container = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)

  useEffect(() => {
    if (!container.current) return
    const instance = new MapLibreMap({ container: container.current, style: STYLE_URL, center: GWANGJU, zoom: 11.2 })
    instance.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    instance.on('load', () => {
      for (const line of LINES) {
        instance.addSource(line.id, { type: 'geojson', data: collection([]) })
        if (line.id === 'route-main') {
          instance.addLayer({
            id: ROUTE_CASING.id, type: 'line', source: line.id,
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': ROUTE_CASING.color, 'line-width': ROUTE_CASING.width },
          })
        }
        instance.addLayer({
          id: line.id, type: 'line', source: line.id,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': line.color, 'line-width': line.width, 'line-opacity': line.opacity,
            ...(line.dash ? { 'line-dasharray': line.dash } : {}),
          },
        })
      }
      setMap(instance)
    })
    return () => instance.remove()
  }, [])

  useEffect(() => {
    if (!map) return
    setLines(map, 'route-main', route ? [route] : [])
    setLines(map, 'route-baseline', baseline && showBaseline ? [baseline] : [])
    setLines(map, 'route-alternatives', alternatives)
  }, [map, route, baseline, alternatives, showBaseline])

  useEffect(() => {
    if (!map) return
    const markers = [
      origin && new Marker({ color: '#16a34a' }).setLngLat([origin.lon, origin.lat]).addTo(map),
      destination && new Marker({ color: '#dc2626' }).setLngLat([destination.lon, destination.lat]).addTo(map),
    ]
    return () => markers.forEach(m => m?.remove())
  }, [map, origin, destination])

  useEffect(() => {
    // Fit the whole route after each new result (requirement 6.1), or the chosen points before that.
    if (!map) return
    const points: LonLat[] = []
    if (route) points.push(...route.coordinates, ...(baseline?.coordinates ?? []))
    else {
      if (origin) points.push([origin.lon, origin.lat])
      if (destination) points.push([destination.lon, destination.lat])
    }
    if (points.length === 0) return
    if (points.length === 1) {
      map.easeTo({ center: points[0], zoom: Math.max(map.getZoom(), 13) })
      return
    }
    const bounds = points.reduce((b, p) => b.extend(p), new LngLatBounds(points[0], points[0]))
    const padding = { top: 56, right: 56, bottom: 72, left: floatingCard ? CARD_SPACE_PX : 56 }
    map.fitBounds(bounds, { padding, maxZoom: 15, duration: 600 })
  }, [map, route, baseline, origin, destination, floatingCard])

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" aria-label="경로 지도" role="region" />
      {map && zoneTypes && (
        <RiskLayer map={map} zones={zones} zoneTypes={zoneTypes} highlightTypes={highlightTypes}
          passedZoneIds={passedZoneIds} />
      )}
    </div>
  )
}
