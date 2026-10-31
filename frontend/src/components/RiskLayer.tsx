import { useEffect, useRef } from 'react'
import { Popup, type ExpressionSpecification, type MapLibreMap, type MapLayerMouseEvent } from 'maplibre-gl'

import { typeCoverage } from '@/lib/level'
import { dummyNotice, zoneCenter, zoneTypesWithData } from '@/lib/zones'
import type { AppConfig, ZoneFeatureCollection, ZoneGroup, ZoneProperties, ZoneType } from '@/lib/types'

const SOURCE = 'risk-zones'
const FILL = 'risk-zones-fill'
const OUTLINE = 'risk-zones-outline'
const DOT_SOURCE = 'risk-zones-dots'
const DOTS = 'risk-zones-dots'
const HEAT = 'risk-zones-heat'
// Underpass dots go under the route line: a road passing over a tunnel must not look like driving through it.
const UNDER_DOTS = 'risk-zones-dots-under'
// Most zones are too small to see when the whole city is in view, so they also get a dot until this zoom.
const DOT_MAX_ZOOM = 14.5
// From afar, hundreds of flood records read as a distribution. Close up, each zone is drawn and can be opened.
const ZONES_FROM_ZOOM = 12.5
const ZONES_FULL_ZOOM = 14
const HEAT_COLORS: ExpressionSpecification = ['interpolate', ['linear'], ['heatmap-density'],
  0, 'rgba(245, 158, 11, 0)', 0.3, 'rgba(245, 158, 11, 0.35)', 0.7, 'rgba(234, 138, 6, 0.65)', 1, 'rgba(217, 119, 6, 0.85)']
const EMPTY = { type: 'FeatureCollection' as const, features: [] }
// Route layers are added by MapView first; zones go underneath them.
const BELOW = 'route-alternatives'

interface Props {
  map: MapLibreMap
  zones: ZoneFeatureCollection | null
  zoneTypes: AppConfig['zone_types']
  zoneGroups: AppConfig['zone_groups']
  highlightGroups: ZoneGroup[]
  passedZoneIds: string[]
  avoidedZoneIds: string[]
}

function zoneDots(zones: ZoneFeatureCollection) {
  return {
    type: 'FeatureCollection' as const,
    features: zones.features.map(feature => ({
      type: 'Feature' as const,
      properties: feature.properties,
      geometry: { type: 'Point' as const, coordinates: zoneCenter(feature.geometry) },
    })),
  }
}

// MapLibre turns null feature properties into the string "null" or drops them.
function numberOrNull(value: unknown): number | null {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

function present(value: unknown): string | null {
  return typeof value === 'string' && value && value !== 'null' ? value : null
}

function popupContent(p: ZoneProperties, typeLabel: string, tierLabel: string | null): HTMLElement {
  const root = document.createElement('div')
  root.className = 'risk-popup'
  const title = document.createElement('strong')
  title.textContent = p.name
  root.append(title)
  const rows: [string, string][] = [['유형', typeLabel]]
  // Terrain tier (design.md 5.8): decides from which rain level the zone is avoided. Not a safety grade.
  const reason = present(p.tier_reason)
  if (tierLabel) rows.push(['회피 등급', reason && reason !== tierLabel ? `${tierLabel} (${reason})` : tierLabel])
  const count = numberOrNull(p.flood_count)
  if (count !== null) rows.push(['침수 기록', `${count}개 연도`])
  const elev = numberOrNull(p.elev_m)
  const low = numberOrNull(p.low_pct)
  if (elev !== null) {
    rows.push(['고도', low !== null ? `해발 ${elev}m · 반경 500m 안 더 낮은 땅 ${low}%` : `해발 ${elev}m`])
  }
  rows.push(['확인일', p.checked_at])
  for (const [k, v] of rows) {
    const row = document.createElement('div')
    row.textContent = `${k}: ${v}`
    root.append(row)
  }
  if (tierLabel) {
    const note = document.createElement('div')
    note.className = 'risk-popup-note'
    note.textContent = '고도(90m 격자)는 참고용이며, 침수 기록이 있는 곳입니다.'
    root.append(note)
  }
  const source = document.createElement('div')
  source.append('출처: ')
  const link = document.createElement('a')
  link.href = p.source_url
  link.target = '_blank'
  link.rel = 'noreferrer'
  link.textContent = p.source_name
  source.append(link)
  root.append(source)
  if (p.is_dummy) {
    const dummy = document.createElement('div')
    dummy.className = 'risk-popup-dummy'
    dummy.textContent = '더미 데이터 — 실제 자료 아님'
    root.append(dummy)
  }
  return root
}

export default function RiskLayer({ map, zones, zoneTypes, zoneGroups, highlightGroups, passedZoneIds, avoidedZoneIds }: Props) {
  const notice = dummyNotice(zones, zoneTypes)
  // What the map may hide from afar stays out of reach too: an invisible zone must not open a popup.
  const markedIds = useRef<string[]>([])
  useEffect(() => {
    if (!map.getSource(SOURCE)) {
      map.addSource(SOURCE, { type: 'geojson', data: EMPTY })
      map.addSource(DOT_SOURCE, { type: 'geojson', data: EMPTY })
      const before = map.getLayer(BELOW) ? BELOW : undefined
      map.addLayer({
        id: HEAT, type: 'heatmap', source: DOT_SOURCE, maxzoom: DOT_MAX_ZOOM, filter: ['==', ['get', 'type'], 'flood_history'],
        paint: {
          'heatmap-color': HEAT_COLORS,
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 10, 0.5, 14, 1.2],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 10, 12, 14, 30],
        },
      }, before)
      map.addLayer({
        id: UNDER_DOTS, type: 'circle', source: DOT_SOURCE, maxzoom: DOT_MAX_ZOOM,
        paint: { 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 0, 'circle-radius': 3.5, 'circle-opacity': 0.95 },
      }, before)
      map.addLayer({ id: FILL, type: 'fill', source: SOURCE }, before)
      map.addLayer({ id: OUTLINE, type: 'line', source: SOURCE, paint: { 'line-width': 1.5 } }, before)
      map.addLayer({
        id: DOTS, type: 'circle', source: DOT_SOURCE, maxzoom: DOT_MAX_ZOOM,
        paint: { 'circle-stroke-color': '#ffffff' },
      })
    }
    const colors: ['match', ['get', string], string, string, string, string, string, string, string] = [
      'match', ['get', 'type'],
      'underpass', zoneTypes.underpass.color,
      'flood_history', zoneTypes.flood_history.color,
      'riverside', zoneTypes.riverside.color,
      '#6b7280']
    map.setPaintProperty(FILL, 'fill-color', colors)
    map.setPaintProperty(OUTLINE, 'line-color', colors)
    map.setPaintProperty(DOTS, 'circle-color', colors)
    map.setPaintProperty(UNDER_DOTS, 'circle-color', colors)

    function shown(event: MapLayerMouseEvent) {
      const feature = event.features?.[0]
      if (!feature) return null
      const props = feature.properties as unknown as ZoneProperties
      const hidden = map.getZoom() < ZONES_FROM_ZOOM && props.type !== 'underpass' && !markedIds.current.includes(props.id)
      return hidden ? null : props
    }

    function onClick(event: MapLayerMouseEvent) {
      const props = shown(event)
      if (!props) return
      const label = zoneTypes[props.type]?.label ?? props.type
      const tierLabel = zoneGroups[props.group]?.tier_label ?? null
      new Popup({ maxWidth: '280px' }).setLngLat(event.lngLat)
        .setDOMContent(popupContent(props, label, tierLabel)).addTo(map)
    }
    const enter = (event: MapLayerMouseEvent) => { map.getCanvas().style.cursor = shown(event) ? 'pointer' : '' }
    const leave = () => { map.getCanvas().style.cursor = '' }
    for (const layer of [FILL, DOTS, UNDER_DOTS]) {
      map.on('click', layer, onClick)
      map.on('mousemove', layer, enter)
      map.on('mouseleave', layer, leave)
    }
    return () => {
      for (const layer of [FILL, DOTS, UNDER_DOTS]) {
        map.off('click', layer, onClick)
        map.off('mousemove', layer, enter)
        map.off('mouseleave', layer, leave)
      }
    }
  }, [map, zoneTypes, zoneGroups])

  useEffect(() => {
    const source = map.getSource(SOURCE)
    if (source && 'setData' in source && zones) {
      (source as { setData: (data: unknown) => void }).setData(zones)
      const dots = map.getSource(DOT_SOURCE) as unknown as { setData: (data: unknown) => void }
      dots.setData(zoneDots(zones))
    }
  }, [map, zones])

  useEffect(() => {
    // Groups avoided at the current level (design.md 5.8) and zones the route passes are drawn strongly,
    // the others faintly (requirement 3.6). A passed zone must stand out even when it is not avoided.
    const onRoute: ExpressionSpecification = ['in', ['get', 'id'], ['literal', passedZoneIds]]
    const avoided: ExpressionSpecification = ['in', ['get', 'id'], ['literal', avoidedZoneIds]]
    const underpass: ExpressionSpecification = ['==', ['get', 'type'], 'underpass']
    const strong: ExpressionSpecification = ['any', ['in', ['get', 'group'], ['literal', highlightGroups]], onRoute]
    const always: ExpressionSpecification = ['any', underpass, onRoute, avoided]
    markedIds.current = [...passedZoneIds, ...avoidedZoneIds]
    // Underpasses and this route's zones are visible at every zoom, the other zones only close up.
    map.setPaintProperty(FILL, 'fill-opacity', ['interpolate', ['linear'], ['zoom'],
      ZONES_FROM_ZOOM, ['case', always, 0.6, 0], ZONES_FULL_ZOOM, ['case', strong, 0.6, 0.2]])
    map.setPaintProperty(OUTLINE, 'line-opacity', ['interpolate', ['linear'], ['zoom'],
      ZONES_FROM_ZOOM, ['case', always, 1, 0], ZONES_FULL_ZOOM, ['case', strong, 1, 0.5]])
    map.setFilter(UNDER_DOTS, ['all', underpass, ['!', onRoute], ['!', avoided]])
    map.setFilter(DOTS, ['any', onRoute, avoided])
    map.setPaintProperty(DOTS, 'circle-radius', ['case', onRoute, 6, 4])
    map.setPaintProperty(DOTS, 'circle-opacity', ['case', onRoute, 0.95, 0.5])
    map.setPaintProperty(DOTS, 'circle-stroke-width', ['case', onRoute, 1.5, 0])
    // Stronger when this rain level avoids flood records, fading out as the zones themselves appear.
    const floodAvoided = highlightGroups.some(group => group.startsWith('flood_history'))
    map.setPaintProperty(HEAT, 'heatmap-opacity', ['interpolate', ['linear'], ['zoom'],
      ZONES_FROM_ZOOM, floodAvoided ? 0.85 : 0.55, DOT_MAX_ZOOM, 0])
  }, [map, highlightGroups, passedZoneIds, avoidedZoneIds, zoneTypes])

  const groupConfig = { zone_groups: zoneGroups }
  const shownTypes = zoneTypesWithData(zones)
  return (
    <div className="pointer-events-none absolute top-2 left-2 z-10 max-w-[calc(100%-4rem)] rounded-lg bg-background/80 p-2 text-[11px] leading-4 shadow ring-1 ring-foreground/10 backdrop-blur lg:top-auto lg:bottom-2 lg:p-2.5 lg:text-xs">
      <p className="mb-1 font-medium">위험 구역</p>
      <ul className="flex flex-wrap gap-x-3 gap-y-1">
        {(Object.keys(zoneTypes) as ZoneType[]).filter(type => shownTypes.has(type)).map(type => {
          const coverage = typeCoverage(type, highlightGroups, groupConfig)
          return (
            <li key={type} className="flex items-center gap-2">
              {/* Shape as well as colour: an underpass is a stretch of road, a flood record a spot. */}
              <span className={`legend-mark legend-mark-${type}`} style={{ background: zoneTypes[type].color }} />
              <span className={coverage === 'none' ? '' : 'font-semibold'}>
                {zoneTypes[type].label}
                {coverage === 'all' ? ' · 회피 대상' : coverage === 'some' ? ' · 일부 회피 대상' : ''}
              </span>
            </li>
          )
        })}
      </ul>
      {shownTypes.has('flood_history') && <p className="mt-1">넓게 보면 색 번짐은 침수 기록 분포이며, 위험도가 아닙니다.</p>}
      {notice && <p className="mt-1 font-medium text-amber-200">{notice}</p>}
      <p className="mt-0.5 text-muted-foreground">기준일 {zones?.metadata.data_checked_at ?? '-'}</p>
    </div>
  )
}
