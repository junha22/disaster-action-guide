import type { MapLibreMap } from 'maplibre-gl'

import type { TimeOfDay } from './scene'

export type MapThemeName = 'light' | 'dark'

export interface MapTheme {
  name: MapThemeName
  styleUrl: string
  baseline: string
  alternatives: string
  travelled: string
  buildings: string
}

const THEMES: Record<MapThemeName, MapTheme> = {
  light: {
    name: 'light',
    styleUrl: 'https://tiles.openfreemap.org/styles/positron',
    baseline: '#334155',
    alternatives: '#7c3aed',
    travelled: '#64748b',
    buildings: '#d8d4cc',
  },
  dark: {
    name: 'dark',
    styleUrl: 'https://tiles.openfreemap.org/styles/fiord',
    baseline: '#e2e8f0',
    alternatives: '#c4b5fd',
    travelled: '#94a3b8',
    buildings: '#2b3650',
  },
}

export function mapThemeFor(time: TimeOfDay): MapTheme {
  return THEMES[time === 'night' ? 'dark' : 'light']
}

// The styles print latin and local names together. Road numbers (shields) keep their own field.
export function applyKoreanLabels(map: MapLibreMap) {
  for (const layer of map.getStyle().layers) {
    if (layer.type !== 'symbol' || !JSON.stringify(layer.layout?.['text-field'] ?? '').includes('name')) continue
    map.setLayoutProperty(layer.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name:nonlatin'], ['get', 'name']])
  }
}

const STYLE_RETRIES = 3
const STYLE_RETRY_MS = 2000

// A style that fails to download leaves the map blank with nothing drawn on it, so try again.
export function retryStyleOnFailure(map: MapLibreMap, styleUrl: string, onGiveUp?: () => void) {
  let attempts = 0
  let timer = 0
  map.on('error', event => {
    if (!String(event.error?.message).includes('/styles/')) return
    if (attempts >= STYLE_RETRIES) {
      onGiveUp?.()
      return
    }
    attempts += 1
    timer = window.setTimeout(() => map.setStyle(styleUrl), STYLE_RETRY_MS)
  })
  map.once('remove', () => window.clearTimeout(timer))
}
