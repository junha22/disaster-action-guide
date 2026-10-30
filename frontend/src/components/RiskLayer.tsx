import { useEffect } from 'react'
import { Popup, type MapLibreMap, type MapLayerMouseEvent } from 'maplibre-gl'

import type { AppConfig, ZoneFeatureCollection, ZoneProperties, ZoneType } from '@/lib/types'

const SOURCE = 'risk-zones'
const FILL = 'risk-zones-fill'
const OUTLINE = 'risk-zones-outline'
const EMPTY = { type: 'FeatureCollection' as const, features: [] }
// Route layers are added by MapView first; zones go underneath them.
const BELOW = 'route-alternatives'

interface Props {
  map: MapLibreMap
  zones: ZoneFeatureCollection | null
  zoneTypes: AppConfig['zone_types']
  highlightTypes: ZoneType[]
}

function popupContent(p: ZoneProperties, typeLabel: string): HTMLElement {
  const root = document.createElement('div')
  root.className = 'risk-popup'
  const title = document.createElement('strong')
  title.textContent = p.name
  root.append(title)
  const rows: [string, string][] = [['유형', typeLabel], ['확인일', p.checked_at]]
  for (const [k, v] of rows) {
    const row = document.createElement('div')
    row.textContent = `${k}: ${v}`
    root.append(row)
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

export default function RiskLayer({ map, zones, zoneTypes, highlightTypes }: Props) {
  useEffect(() => {
    if (!map.getSource(SOURCE)) {
      map.addSource(SOURCE, { type: 'geojson', data: EMPTY })
      const before = map.getLayer(BELOW) ? BELOW : undefined
      map.addLayer({ id: FILL, type: 'fill', source: SOURCE }, before)
      map.addLayer({ id: OUTLINE, type: 'line', source: SOURCE, paint: { 'line-width': 1.5 } }, before)
    }
    const colors: ['match', ['get', string], string, string, string, string, string, string, string] = [
      'match', ['get', 'type'],
      'underpass', zoneTypes.underpass.color,
      'flood_history', zoneTypes.flood_history.color,
      'riverside', zoneTypes.riverside.color,
      '#6b7280']
    map.setPaintProperty(FILL, 'fill-color', colors)
    map.setPaintProperty(OUTLINE, 'line-color', colors)

    function onClick(event: MapLayerMouseEvent) {
      const feature = event.features?.[0]
      if (!feature) return
      const props = feature.properties as unknown as ZoneProperties
      const label = zoneTypes[props.type]?.label ?? props.type
      new Popup({ maxWidth: '260px' }).setLngLat(event.lngLat).setDOMContent(popupContent(props, label)).addTo(map)
    }
    const enter = () => { map.getCanvas().style.cursor = 'pointer' }
    const leave = () => { map.getCanvas().style.cursor = '' }
    map.on('click', FILL, onClick)
    map.on('mouseenter', FILL, enter)
    map.on('mouseleave', FILL, leave)
    return () => {
      map.off('click', FILL, onClick)
      map.off('mouseenter', FILL, enter)
      map.off('mouseleave', FILL, leave)
    }
  }, [map, zoneTypes])

  useEffect(() => {
    const source = map.getSource(SOURCE)
    if (source && 'setData' in source && zones) {
      (source as { setData: (data: unknown) => void }).setData(zones)
    }
  }, [map, zones])

  useEffect(() => {
    // Types avoided at the current level are drawn strongly, the others faintly (requirement 3.6).
    const strong = highlightTypes.length > 0
    map.setPaintProperty(FILL, 'fill-opacity',
      strong ? ['match', ['get', 'type'], highlightTypes, 0.55, 0.12] : 0.12)
    map.setPaintProperty(OUTLINE, 'line-opacity',
      strong ? ['match', ['get', 'type'], highlightTypes, 1, 0.35] : 0.35)
  }, [map, highlightTypes, zoneTypes])

  return (
    <div className="pointer-events-none absolute top-2 left-2 z-10 rounded-lg bg-background/90 p-2 text-[11px] leading-4 shadow ring-1 ring-foreground/10 lg:p-2.5 lg:text-xs">
      <p className="mb-1.5 font-medium">위험 구역</p>
      <ul className="space-y-1">
        {(Object.keys(zoneTypes) as ZoneType[]).map(type => (
          <li key={type} className="flex items-center gap-2">
            <span className="inline-block size-3 rounded-sm"
              style={{ background: zoneTypes[type].color, opacity: highlightTypes.includes(type) ? 1 : 0.35 }} />
            <span className={highlightTypes.includes(type) ? 'font-semibold' : 'text-muted-foreground'}>
              {zoneTypes[type].label}{highlightTypes.includes(type) ? ' · 피함' : ''}
            </span>
          </li>
        ))}
      </ul>
      {zones?.metadata.has_dummy && (
        <p className="mt-1.5 font-medium text-orange-700">더미 데이터 — 실제 자료 아님</p>
      )}
      <p className="mt-0.5 text-muted-foreground">기준일 {zones?.metadata.data_checked_at ?? '-'}</p>
    </div>
  )
}
