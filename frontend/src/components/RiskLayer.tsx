import { useEffect } from 'react'
import { Popup, type ExpressionSpecification, type MapLibreMap, type MapLayerMouseEvent } from 'maplibre-gl'

import { typeCoverage } from '@/lib/level'
import { dummyNotice, zoneCenter, zoneTypesWithData } from '@/lib/zones'
import type { AppConfig, ZoneFeatureCollection, ZoneGroup, ZoneProperties, ZoneType } from '@/lib/types'

const SOURCE = 'risk-zones'
const FILL = 'risk-zones-fill'
const OUTLINE = 'risk-zones-outline'
const DOT_SOURCE = 'risk-zones-dots'
const DOTS = 'risk-zones-dots'
// Most zones are too small to see when the whole city is in view, so they also get a dot until this zoom.
const DOT_MAX_ZOOM = 14.5
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

export default function RiskLayer({ map, zones, zoneTypes, zoneGroups, highlightGroups, passedZoneIds }: Props) {
  const notice = dummyNotice(zones, zoneTypes)
  useEffect(() => {
    if (!map.getSource(SOURCE)) {
      map.addSource(SOURCE, { type: 'geojson', data: EMPTY })
      map.addSource(DOT_SOURCE, { type: 'geojson', data: EMPTY })
      const before = map.getLayer(BELOW) ? BELOW : undefined
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

    function onClick(event: MapLayerMouseEvent) {
      const feature = event.features?.[0]
      if (!feature) return
      const props = feature.properties as unknown as ZoneProperties
      const label = zoneTypes[props.type]?.label ?? props.type
      const tierLabel = zoneGroups[props.group]?.tier_label ?? null
      new Popup({ maxWidth: '280px' }).setLngLat(event.lngLat)
        .setDOMContent(popupContent(props, label, tierLabel)).addTo(map)
    }
    const enter = () => { map.getCanvas().style.cursor = 'pointer' }
    const leave = () => { map.getCanvas().style.cursor = '' }
    for (const layer of [FILL, DOTS]) {
      map.on('click', layer, onClick)
      map.on('mouseenter', layer, enter)
      map.on('mouseleave', layer, leave)
    }
    return () => {
      for (const layer of [FILL, DOTS]) {
        map.off('click', layer, onClick)
        map.off('mouseenter', layer, enter)
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
    const strong: ExpressionSpecification = ['any', ['in', ['get', 'group'], ['literal', highlightGroups]], onRoute]
    map.setPaintProperty(FILL, 'fill-opacity', ['case', strong, 0.6, 0.2])
    map.setPaintProperty(OUTLINE, 'line-opacity', ['case', strong, 1, 0.5])
    // Real data has hundreds of zones: only those on the route get a full marker, or the map fills up.
    map.setPaintProperty(DOTS, 'circle-radius', ['case', onRoute, 6, strong, 3, 2])
    map.setPaintProperty(DOTS, 'circle-opacity', ['case', strong, 0.95, 0.4])
    map.setPaintProperty(DOTS, 'circle-stroke-width', ['case', onRoute, 1.5, 0])
  }, [map, highlightGroups, passedZoneIds, zoneTypes])

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
              <span className="inline-block size-3 rounded-sm"
                style={{ background: zoneTypes[type].color, opacity: coverage === 'none' ? 0.35 : 1 }} />
              <span className={coverage === 'none' ? 'text-muted-foreground' : 'font-semibold'}>
                {zoneTypes[type].label}
                {coverage === 'all' ? ' · 회피 대상' : coverage === 'some' ? ' · 일부 회피 대상' : ''}
              </span>
            </li>
          )
        })}
      </ul>
      {notice && <p className="mt-1 font-medium text-amber-200">{notice}</p>}
      <p className="mt-0.5 text-muted-foreground">기준일 {zones?.metadata.data_checked_at ?? '-'}</p>
    </div>
  )
}
