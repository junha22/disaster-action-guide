// Geometry and turn logic for the driving screen. All distances are metres along the route.
import type { GuidanceStep, LonLat, StepKind, ZoneFeatureCollection } from './types'
import { zoneCenter } from './zones'

export const STEP_LABELS: Record<StepKind, string> = {
  depart: '출발',
  arrive: '목적지 도착',
  straight: '직진',
  slight_left: '왼쪽 방향',
  left: '좌회전',
  sharp_left: '급좌회전',
  slight_right: '오른쪽 방향',
  right: '우회전',
  sharp_right: '급우회전',
  uturn: '유턴',
  merge: '합류',
  roundabout: '회전교차로',
}

function metres(a: LonLat, b: LonLat): number {
  const mid = ((a[1] + b[1]) / 2) * (Math.PI / 180)
  return Math.hypot((a[1] - b[1]) * 110_574, (a[0] - b[0]) * 111_320 * Math.cos(mid))
}

function bearing(a: LonLat, b: LonLat): number {
  const mid = ((a[1] + b[1]) / 2) * (Math.PI / 180)
  return (Math.atan2((b[0] - a[0]) * Math.cos(mid), b[1] - a[1]) * 180) / Math.PI
}

export interface Track {
  coordinates: LonLat[]
  along: number[]
  length: number
}

export function buildTrack(coordinates: LonLat[]): Track {
  const along = [0]
  for (let i = 1; i < coordinates.length; i++) along.push(along[i - 1] + metres(coordinates[i - 1], coordinates[i]))
  return { coordinates, along, length: along[along.length - 1] ?? 0 }
}

function segmentAt(track: Track, distance: number): number {
  let low = 0
  let high = track.along.length - 1
  while (high - low > 1) {
    const middle = (low + high) >> 1
    if (track.along[middle] <= distance) low = middle
    else high = middle
  }
  return low
}

export function pointAt(track: Track, distance: number): LonLat {
  const d = Math.max(0, Math.min(distance, track.length))
  const i = segmentAt(track, d)
  const a = track.coordinates[i]
  const b = track.coordinates[i + 1] ?? a
  const span = track.along[i + 1] - track.along[i]
  const t = span > 0 ? (d - track.along[i]) / span : 0
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

// Looks a little ahead so the map turns into a corner instead of snapping at it.
export function headingAt(track: Track, distance: number, lookAhead = 45): number {
  const from = pointAt(track, distance)
  const to = pointAt(track, distance + lookAhead)
  return from[0] === to[0] && from[1] === to[1] ? 0 : bearing(from, to)
}

export function splitTrack(track: Track, distance: number): { done: LonLat[]; left: LonLat[] } {
  const d = Math.max(0, Math.min(distance, track.length))
  const i = segmentAt(track, d)
  const here = pointAt(track, d)
  return {
    done: [...track.coordinates.slice(0, i + 1), here],
    left: [here, ...track.coordinates.slice(i + 1)],
  }
}

export interface PlacedStep extends GuidanceStep {
  start: number
  speedKph: number
}

// Engine step lengths and the drawn line can differ by a few metres; stretch steps to fit the line.
export function placeSteps(steps: GuidanceStep[], track: Track): PlacedStep[] {
  const total = steps.reduce((sum, step) => sum + step.distance_m, 0)
  const scale = total > 0 ? track.length / total : 1
  let start = 0
  return steps.map(step => {
    const placed = {
      ...step,
      start,
      speedKph: step.duration_s > 0 ? (step.distance_m / step.duration_s) * 3.6 : 0,
    }
    start += step.distance_m * scale
    return placed
  })
}

export function stepIndexAt(steps: PlacedStep[], distance: number): number {
  let index = 0
  for (let i = 0; i < steps.length; i++) {
    if (steps[i].start <= distance) index = i
  }
  return index
}

export interface ZoneOnTrack {
  id: string
  name: string
  at: number
  gap: number
}

// Where along the route each zone is closest. `gap` is how far the route stays from its centre.
export function placeZones(zones: ZoneFeatureCollection | null, ids: string[], track: Track): ZoneOnTrack[] {
  if (!zones) return []
  const wanted = new Set(ids)
  return zones.features.filter(feature => wanted.has(feature.properties.id)).map(feature => {
    const center = zoneCenter(feature.geometry)
    let best = 0
    let gap = Infinity
    track.coordinates.forEach((point, i) => {
      const distance = metres(point, center)
      if (distance < gap) {
        gap = distance
        best = i
      }
    })
    return { id: feature.properties.id, name: feature.properties.name, at: track.along[best], gap }
  })
}
