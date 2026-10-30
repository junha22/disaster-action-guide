import type { AppConfig, LonLat, ZoneFeatureCollection, ZoneType } from './types'

function collectPositions(coordinates: unknown, into: LonLat[]) {
  if (!Array.isArray(coordinates)) return
  if (typeof coordinates[0] === 'number') {
    into.push(coordinates as LonLat)
    return
  }
  coordinates.forEach(child => collectPositions(child, into))
}

export function zoneCenter(geometry: unknown): LonLat {
  const positions: LonLat[] = []
  collectPositions((geometry as { coordinates?: unknown }).coordinates, positions)
  const lons = positions.map(p => p[0])
  const lats = positions.map(p => p[1])
  return [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2]
}

// Only some types may still be placeholders, so name them instead of calling all zones dummy data.
export function dummyNotice(zones: ZoneFeatureCollection | null, zoneTypes: AppConfig['zone_types'] | null | undefined): string {
  if (!zones?.metadata.has_dummy) return ''
  const types = new Set<ZoneType>(zones.features.filter(f => f.properties.is_dummy).map(f => f.properties.type))
  const labels = [...types].map(type => zoneTypes?.[type]?.label ?? type)
  return `${labels.join('·')}: 더미 데이터`
}
