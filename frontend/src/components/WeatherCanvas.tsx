import { useEffect, useRef } from 'react'

import { useReducedMotion } from '@/lib/media'
import type { Rgb, SceneSpec } from '@/lib/scene'

// Decorative only: hidden from assistive tech, the weather is stated in text elsewhere.
// Weather shows as colour, light, haze and rain rather than drawn objects.
const VARIANTS = {
  page: { sky: true, glow: false, ripples: false, flash: 0.16, maxDpr: 1, fogAlpha: 1, rainAlpha: 1 },
  hero: { sky: true, glow: true, ripples: true, flash: 0.35, maxDpr: 2, fogAlpha: 1, rainAlpha: 1 },
  map: { sky: false, glow: false, ripples: false, flash: 0.08, maxDpr: 1, fogAlpha: 0.5, rainAlpha: 0.45 },
}

const MAX_DROPS = 280
const MIN_DROPS = 70
const REFERENCE_AREA = 1400 * 900
const RIPPLE_COUNT = 14
const FRAME_MS = 24
const STRIKE_PERIOD_MS = 9000
const STRIKE_MS = 420

function seeded(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function rgb(color: Rgb) {
  return `rgb(${color[0]}, ${color[1]}, ${color[2]})`
}

function strikePower(now: number) {
  const index = Math.floor(now / STRIKE_PERIOD_MS)
  const start = index * STRIKE_PERIOD_MS + seeded(index + 1)() * STRIKE_PERIOD_MS * 0.5
  const age = now - start
  if (age < 0 || age > STRIKE_MS) return 0
  // Two soft pulses per strike, at most one strike every few seconds, for photosensitive users.
  return age < 90 ? 1 - age / 90 : age > 150 && age < 280 ? 0.6 * (1 - (age - 150) / 130) : 0
}

interface Props {
  spec: SceneSpec
  variant: keyof typeof VARIANTS
  className?: string
}

export default function WeatherCanvas({ spec, variant, className = '' }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const specRef = useRef(spec)
  const redrawRef = useRef<(() => void) | null>(null)
  const reduced = useReducedMotion()

  useEffect(() => {
    specRef.current = spec
    redrawRef.current?.()
  }, [spec])

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    const layers = VARIANTS[variant]
    const dpr = Math.min(window.devicePixelRatio || 1, layers.maxDpr)
    const random = seeded(variant.length * 7 + 3)

    let width = 0
    let height = 0
    let frame = 0
    let last = performance.now()
    let drops: { x: number; y: number; length: number; speed: number; weight: number }[] = []
    const ripples = Array.from({ length: RIPPLE_COUNT }, () => ({ x: random(), y: random(), age: random() }))

    // Eased copy of the spec, so changing the weather or the time drifts instead of cutting.
    const start = specRef.current
    const now_: { sky: [Rgb, Rgb, Rgb]; values: Record<string, number> } = {
      sky: start.sky.map(c => [...c]) as [Rgb, Rgb, Rgb],
      values: targets(start),
    }

    function targets(target: SceneSpec): Record<string, number> {
      return {
        fog: target.fog, wind: target.wind, ripple: target.ripple, rain: target.rainIntensity, glow: target.glow,
        dayness: target.time === 'day' ? 1 : 0, sunsetness: target.time === 'sunset' ? 1 : 0, nightness: target.time === 'night' ? 1 : 0,
      }
    }

    function ease(amount: number) {
      const target = specRef.current
      now_.sky.forEach((color, i) => color.forEach((value, c) => { color[c] = value + (target.sky[i][c] - value) * amount }))
      const goals = targets(target)
      for (const key of Object.keys(goals)) now_.values[key] += (goals[key] - now_.values[key]) * amount
    }

    function resize() {
      if (!canvas) return
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      const count = Math.max(MIN_DROPS, Math.ceil(MAX_DROPS * Math.min((width * height) / REFERENCE_AREA, 1.5)))
      drops = Array.from({ length: count }, () => ({
        x: random() * width * 1.5,
        y: random() * height,
        length: 10 + random() * 18,
        speed: 650 + random() * 500,
        weight: random() < 0.15 ? 1.5 : 1,
      }))
    }

    function drawSky(c: CanvasRenderingContext2D) {
      const gradient = c.createLinearGradient(0, 0, 0, height)
      gradient.addColorStop(0, rgb(now_.sky[0]))
      gradient.addColorStop(0.55, rgb(now_.sky[1]))
      gradient.addColorStop(1, rgb(now_.sky[2]))
      c.fillStyle = gradient
      c.fillRect(0, 0, width, height)
    }

    // Light from beyond the top corner: warm by day and at sunset, faint and cool at night.
    function drawGlow(c: CanvasRenderingContext2D) {
      const { glow, dayness, sunsetness, nightness } = now_.values
      if (glow < 0.02) return
      const colour = sunsetness > dayness && sunsetness > nightness ? '255, 176, 120' : nightness > dayness ? '170, 195, 245' : '255, 240, 210'
      const strength = (nightness > dayness && nightness > sunsetness ? 0.22 : 0.5) * glow
      const x = width * 0.82
      const radius = Math.max(width, height) * 0.8
      const light = c.createRadialGradient(x, -height * 0.2, 0, x, -height * 0.2, radius)
      light.addColorStop(0, `rgba(${colour}, ${strength})`)
      light.addColorStop(1, `rgba(${colour}, 0)`)
      c.fillStyle = light
      c.fillRect(0, 0, width, height)
    }

    function drawFog(c: CanvasRenderingContext2D, clock: number) {
      const fog = now_.values.fog * layers.fogAlpha
      if (fog < 0.02) return
      for (let i = 0; i < 3; i++) {
        const y = height * (0.2 + i * 0.3) + Math.sin(clock * 0.00022 + i * 2) * height * 0.05
        const size = height * 0.3
        const band = c.createLinearGradient(0, y - size, 0, y + size)
        band.addColorStop(0, 'rgba(190, 202, 216, 0)')
        band.addColorStop(0.5, `rgba(190, 202, 216, ${fog * 0.34})`)
        band.addColorStop(1, 'rgba(190, 202, 216, 0)')
        c.fillStyle = band
        c.fillRect(0, y - size, width, size * 2)
      }
    }

    function drawRain(c: CanvasRenderingContext2D, elapsed: number) {
      const { rain, wind } = now_.values
      if (rain <= 0.005) return
      const visible = Math.ceil(drops.length * Math.min(rain * 1.15, 1))
      const pace = 0.75 + rain * 0.65
      const stretch = 0.8 + rain * 0.9
      // Pale drops vanish on the light daytime map, so they turn slate there.
      const dropColor = variant === 'map' && now_.values.nightness < 0.5 ? '60, 85, 120' : '210, 228, 255'
      for (const weight of [1, 1.5]) {
        c.strokeStyle = `rgba(${dropColor}, ${(0.3 + rain * 0.34) * layers.rainAlpha * (weight > 1 ? 1 : 0.8)})`
        c.lineWidth = weight
        c.lineCap = 'round'
        c.beginPath()
        for (let i = 0; i < visible; i++) {
          const drop = drops[i]
          if (drop.weight !== weight) continue
          drop.y += drop.speed * pace * elapsed
          drop.x -= drop.speed * pace * elapsed * wind
          if (drop.y > height + 30 || drop.x < -30) {
            drop.y = -30
            drop.x = random() * width * 1.5
          }
          const length = drop.length * stretch
          c.moveTo(drop.x, drop.y)
          c.lineTo(drop.x - length * wind, drop.y + length)
        }
        c.stroke()
      }
    }

    function drawRipples(c: CanvasRenderingContext2D, elapsed: number) {
      const active = Math.round(now_.values.ripple * RIPPLE_COUNT)
      if (active === 0) return
      c.lineWidth = 1
      for (let i = 0; i < active; i++) {
        const ripple = ripples[i]
        ripple.age += elapsed * 1.3
        if (ripple.age >= 1) {
          ripple.age = 0
          ripple.x = random()
          ripple.y = random()
        }
        c.strokeStyle = `rgba(215, 232, 255, ${0.42 * (1 - ripple.age)})`
        c.beginPath()
        c.ellipse(ripple.x * width, height * (0.9 + ripple.y * 0.1), 2 + ripple.age * 18, 1 + ripple.age * 4, 0, 0, Math.PI * 2)
        c.stroke()
      }
    }

    function drawLightning(c: CanvasRenderingContext2D, clock: number) {
      if (!specRef.current.lightning || reduced) return
      const power = strikePower(clock)
      if (power <= 0) return
      c.fillStyle = `rgba(205, 218, 255, ${layers.flash * power})`
      c.fillRect(0, 0, width, height)
    }

    function draw(clock: number, elapsed: number) {
      if (!context) return
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      context.clearRect(0, 0, width, height)
      if (layers.sky) drawSky(context)
      if (layers.glow) drawGlow(context)
      drawFog(context, clock)
      drawRain(context, elapsed)
      if (layers.ripples) drawRipples(context, elapsed)
      drawLightning(context, clock)
    }

    function tick(clock: number) {
      frame = requestAnimationFrame(tick)
      if (clock - last < FRAME_MS) return
      // Clamp the step so a backgrounded tab does not make everything jump at once.
      const elapsed = Math.min((clock - last) / 1000, 0.05)
      last = clock
      ease(1 - Math.exp(-elapsed * 2.2))
      draw(clock, elapsed)
    }

    function still() {
      ease(1)
      draw(performance.now(), 0)
    }

    const observer = new ResizeObserver(() => {
      resize()
      if (reduced) still()
    })
    observer.observe(canvas)
    resize()
    if (reduced) {
      redrawRef.current = still
      still()
    } else {
      frame = requestAnimationFrame(tick)
    }
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
      redrawRef.current = null
    }
  }, [variant, reduced])

  return <canvas ref={canvasRef} aria-hidden="true" className={`pointer-events-none absolute inset-0 size-full ${className}`} />
}
