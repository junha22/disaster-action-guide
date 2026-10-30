// Decorative sky settings. Nothing here affects routing. The API only reports rain and alerts, so a
// dry scene means "no rain measured", not an observed clear sky.
export type TimeOfDay = 'day' | 'sunset' | 'night'
export type SceneKind = 'clear' | 'overcast' | 'drizzle' | 'rain' | 'heavy' | 'downpour' | 'storm'
export type Rgb = [number, number, number]

export interface SceneSpec {
  kind: SceneKind
  time: TimeOfDay
  title: string
  rainIntensity: number
  sky: [Rgb, Rgb, Rgb]
  fog: number
  wind: number
  ripple: number
  lightning: boolean
  glow: number
  mapOverlay: string
}

const CLEAR_SKY: Record<TimeOfDay, [Rgb, Rgb, Rgb]> = {
  day: [[24, 104, 176], [66, 152, 212], [176, 220, 236]],
  sunset: [[42, 44, 104], [186, 78, 122], [250, 168, 98]],
  night: [[6, 10, 34], [16, 30, 68], [32, 52, 92]],
}

const GLOOMY_SKY: Record<TimeOfDay, [Rgb, Rgb, Rgb]> = {
  day: [[42, 54, 66], [72, 84, 96], [108, 120, 132]],
  sunset: [[36, 30, 52], [78, 58, 78], [122, 90, 86]],
  night: [[5, 7, 13], [11, 15, 24], [20, 26, 36]],
}

const KINDS: Record<SceneKind, Pick<SceneSpec, 'fog' | 'wind' | 'ripple' | 'lightning'> & { gloom: number; tint: number }> = {
  clear: { gloom: 0, fog: 0.06, wind: 0.08, ripple: 0, lightning: false, tint: 0 },
  overcast: { gloom: 0.72, fog: 0.3, wind: 0.1, ripple: 0, lightning: false, tint: 0.05 },
  drizzle: { gloom: 0.42, fog: 0.16, wind: 0.08, ripple: 0.2, lightning: false, tint: 0.01 },
  rain: { gloom: 0.62, fog: 0.24, wind: 0.13, ripple: 0.45, lightning: false, tint: 0.03 },
  heavy: { gloom: 0.78, fog: 0.3, wind: 0.2, ripple: 0.7, lightning: false, tint: 0.05 },
  downpour: { gloom: 0.9, fog: 0.42, wind: 0.32, ripple: 1, lightning: false, tint: 0.07 },
  storm: { gloom: 1, fog: 0.46, wind: 0.42, ripple: 1, lightning: true, tint: 0.1 },
}

const RANK: SceneKind[] = ['drizzle', 'rain', 'heavy', 'downpour', 'storm']
// An alert can make the sky look worse than the current rain reading, never better.
const LEVEL_KIND: Record<number, SceneKind> = { 1: 'heavy', 2: 'downpour', 3: 'storm' }

function kindFor(rainMm: number, level: number): SceneKind {
  if (rainMm <= 0) return level > 0 ? 'overcast' : 'clear'
  const byRain: SceneKind = rainMm < 15 ? 'drizzle' : rainMm < 30 ? 'rain' : rainMm < 50 ? 'heavy' : rainMm < 70 ? 'downpour' : 'storm'
  const byLevel = LEVEL_KIND[level]
  return byLevel && RANK.indexOf(byLevel) > RANK.indexOf(byRain) ? byLevel : byRain
}

function rainTitle(rainMm: number): string {
  if (rainMm <= 0) return '비 없음'
  if (rainMm < 15) return '비'
  if (rainMm < 30) return '강한 비'
  if (rainMm < 50) return '매우 강한 비'
  if (rainMm < 70) return '폭우'
  return '극심한 폭우'
}

function mix(a: Rgb, b: Rgb, amount: number): Rgb {
  return [0, 1, 2].map(i => a[i] + (b[i] - a[i]) * amount) as Rgb
}

export function weatherScene(rainMm: number, level: number, time: TimeOfDay): SceneSpec {
  const kind = kindFor(rainMm, level)
  const { gloom, tint, ...rest } = KINDS[kind]
  return {
    ...rest,
    kind,
    time,
    title: rainTitle(rainMm),
    rainIntensity: Math.min(rainMm / 100, 1),
    sky: [0, 1, 2].map(i => mix(CLEAR_SKY[time][i], GLOOMY_SKY[time][i], gloom)) as [Rgb, Rgb, Rgb],
    glow: Math.max(0, 1 - gloom * 1.6),
    // Sunset warms the map even in dry weather; otherwise only rain darkens it, and only slightly.
    mapOverlay: time === 'sunset' ? `rgb(150 80 50 / ${Math.max(tint, 0.1)})` : `rgb(6 10 20 / ${tint})`,
  }
}

export function currentTimeOfDay(now = new Date()): TimeOfDay {
  const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Seoul', hour: 'numeric', hour12: false }).format(now)) % 24
  if (hour >= 7 && hour < 17) return 'day'
  if ((hour >= 17 && hour < 19) || (hour >= 5 && hour < 7)) return 'sunset'
  return 'night'
}
