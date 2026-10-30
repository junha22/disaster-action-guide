import { useEffect, useRef } from 'react'

import { useReducedMotion } from '@/lib/media'
import type { Rgb, SceneSpec, TimeOfDay } from '@/lib/scene'

// Decorative only: hidden from assistive tech, the weather is stated in text elsewhere.
const VARIANTS = {
  page: { sky: true, stars: true, celestial: false, clouds: true, ripples: false, bolts: false, flash: 0.16, maxDpr: 1, cloudSize: 0.3, rainAlpha: 1 },
  hero: { sky: true, stars: true, celestial: true, clouds: true, ripples: true, bolts: true, flash: 0.35, maxDpr: 2, cloudSize: 0.62, rainAlpha: 1 },
  map: { sky: false, stars: false, celestial: false, clouds: false, ripples: false, bolts: false, flash: 0.08, maxDpr: 1, cloudSize: 0, rainAlpha: 0.45 },
}

const MAX_DROPS = 280
const MIN_DROPS = 70
const REFERENCE_AREA = 1400 * 900
const STAR_COUNT = 90
const CLOUD_COUNT = 10
const RIPPLE_COUNT = 14
const CLOUD_VARIANTS = 4
const FRAME_MS = 24
const STRIKE_PERIOD_MS = 9000
const STRIKE_MS = 420
const SHOOTING_STAR_PERIOD_MS = 23000
const SHOOTING_STAR_MS = 900

const CLOUD_LIGHT: Record<TimeOfDay, [string, string]> = {
  day: ['255, 255, 255', '196, 210, 226'],
  sunset: ['255, 214, 190', '176, 112, 136'],
  night: ['112, 128, 160', '48, 58, 84'],
}
const CLOUD_DARK = ['88, 98, 112', '38, 44, 54']

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

function cloudSprite(seed: number, [lit, under]: string[]) {
  const random = seeded(seed)
  const sprite = document.createElement('canvas')
  sprite.width = 520
  sprite.height = 230
  const context = sprite.getContext('2d')
  if (!context) return sprite
  const puffs = Array.from({ length: 30 }, () => {
    const along = random()
    const dome = Math.sin(along * Math.PI)
    return {
      x: 50 + along * 420,
      y: 170 - dome * (40 + random() * 70) + random() * 22,
      radius: (24 + random() * 48) * (0.55 + dome * 0.55),
    }
  })
  for (const puff of puffs) {
    const gradient = context.createRadialGradient(puff.x, puff.y, 0, puff.x, puff.y, puff.radius)
    gradient.addColorStop(0, `rgba(${lit}, 0.95)`)
    gradient.addColorStop(0.55, `rgba(${lit}, 0.6)`)
    gradient.addColorStop(1, `rgba(${lit}, 0)`)
    context.fillStyle = gradient
    context.beginPath()
    context.arc(puff.x, puff.y, puff.radius, 0, Math.PI * 2)
    context.fill()
  }
  context.globalCompositeOperation = 'source-atop'
  const shadow = context.createLinearGradient(0, 70, 0, 215)
  shadow.addColorStop(0, `rgba(${under}, 0)`)
  shadow.addColorStop(1, `rgba(${under}, 0.9)`)
  context.fillStyle = shadow
  context.fillRect(0, 0, sprite.width, sprite.height)
  return sprite
}

function rgb(color: Rgb) {
  return `rgb(${color[0]}, ${color[1]}, ${color[2]})`
}

function strikeAt(now: number) {
  const index = Math.floor(now / STRIKE_PERIOD_MS)
  const start = index * STRIKE_PERIOD_MS + seeded(index + 1)() * STRIKE_PERIOD_MS * 0.5
  const age = now - start
  if (age < 0 || age > STRIKE_MS) return { index, power: 0 }
  // Two soft pulses per strike, at most one strike every few seconds, for photosensitive users.
  const power = age < 90 ? 1 - age / 90 : age > 150 && age < 280 ? 0.6 * (1 - (age - 150) / 130) : 0
  return { index, power }
}

function drawBolt(context: CanvasRenderingContext2D, index: number, power: number, width: number, height: number) {
  const random = seeded(index + 99)
  const branch = (x: number, y: number, steps: number, spread: number, lineWidth: number) => {
    context.lineWidth = lineWidth
    context.beginPath()
    context.moveTo(x, y)
    for (let i = 0; i < steps; i++) {
      x += (random() - 0.5) * spread
      y += (height * 0.72) / 11
      context.lineTo(x, y)
      if (lineWidth > 1 && random() < 0.16) {
        context.stroke()
        branch(x, y, 3, spread * 1.2, lineWidth * 0.5)
        context.lineWidth = lineWidth
        context.beginPath()
        context.moveTo(x, y)
      }
    }
    context.stroke()
  }
  context.save()
  context.strokeStyle = `rgba(226, 234, 255, ${power})`
  context.shadowColor = 'rgba(170, 195, 255, 0.9)'
  context.shadowBlur = 14
  context.lineCap = 'round'
  context.lineJoin = 'round'
  branch(width * (0.2 + random() * 0.6), 0, 11, width * 0.09, 1.8)
  context.restore()
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
  const lightCloudsRef = useRef<HTMLCanvasElement[]>([])
  const reduced = useReducedMotion()
  const time = spec.time

  useEffect(() => {
    lightCloudsRef.current = Array.from({ length: CLOUD_VARIANTS }, (_, i) => cloudSprite(i + 11, CLOUD_LIGHT[time]))
  }, [time])

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
    const dark = Array.from({ length: CLOUD_VARIANTS }, (_, i) => cloudSprite(i + 11, CLOUD_DARK))

    let width = 0
    let height = 0
    let frame = 0
    let last = performance.now()
    let drops: { x: number; y: number; length: number; speed: number; weight: number }[] = []
    const stars = Array.from({ length: STAR_COUNT }, () => ({
      x: random(), y: random() * 0.6, size: 0.7 + random() * 1.1, phase: random() * Math.PI * 2, rate: 0.6 + random() * 1.6,
    }))
    const clouds = Array.from({ length: CLOUD_COUNT }, (_, i) => ({
      sprite: i % CLOUD_VARIANTS, x: random(), y: random(), depth: 0.55 + random() * 0.65,
    }))
    const ripples = Array.from({ length: RIPPLE_COUNT }, () => ({ x: random(), y: random(), age: random() }))

    // Eased copy of the spec, so changing the weather or the time drifts instead of cutting.
    const start = specRef.current
    const now_: { sky: [Rgb, Rgb, Rgb]; values: Record<string, number> } = {
      sky: start.sky.map(c => [...c]) as [Rgb, Rgb, Rgb],
      values: {
        cover: start.cover, shade: start.shade, fog: start.fog, wind: start.wind, ripple: start.ripple,
        rain: start.rainIntensity, celestial: start.celestial, rainbow: start.rainbow,
        dayness: start.time === 'day' ? 1 : 0, sunsetness: start.time === 'sunset' ? 1 : 0, nightness: start.time === 'night' ? 1 : 0,
      },
    }

    function targets(target: SceneSpec): Record<string, number> {
      return {
        cover: target.cover, shade: target.shade, fog: target.fog, wind: target.wind, ripple: target.ripple,
        rain: target.rainIntensity, celestial: target.celestial, rainbow: target.rainbow,
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

    function drawStars(c: CanvasRenderingContext2D, clock: number) {
      const visible = now_.values.nightness * now_.values.celestial
      if (visible < 0.02) return
      for (const star of stars) {
        const twinkle = 0.55 + 0.45 * Math.sin(clock * 0.001 * star.rate + star.phase)
        c.fillStyle = `rgba(235, 240, 255, ${visible * twinkle})`
        c.beginPath()
        c.arc(star.x * width, star.y * height, star.size, 0, Math.PI * 2)
        c.fill()
      }
      const index = Math.floor(clock / SHOOTING_STAR_PERIOD_MS)
      const age = clock - (index * SHOOTING_STAR_PERIOD_MS + seeded(index + 5)() * SHOOTING_STAR_PERIOD_MS * 0.6)
      if (age > 0 && age < SHOOTING_STAR_MS) {
        const seed = seeded(index + 6)
        const progress = age / SHOOTING_STAR_MS
        const x = width * (0.15 + seed() * 0.5) + progress * width * 0.35
        const y = height * (0.04 + seed() * 0.12) + progress * height * 0.16
        const tail = c.createLinearGradient(x, y, x - 46, y - 20)
        tail.addColorStop(0, `rgba(255, 255, 255, ${visible * (1 - progress)})`)
        tail.addColorStop(1, 'rgba(255, 255, 255, 0)')
        c.strokeStyle = tail
        c.lineWidth = 1.4
        c.beginPath()
        c.moveTo(x, y)
        c.lineTo(x - 46, y - 20)
        c.stroke()
      }
    }

    function drawRainbow(c: CanvasRenderingContext2D) {
      const visible = now_.values.rainbow
      if (visible < 0.02) return
      const colors = ['255, 92, 92', '255, 165, 72', '255, 232, 110', '110, 224, 140', '100, 180, 255', '170, 130, 255']
      // Sized in pixels so the top of the arc sits in the clear band above the card's text.
      const radius = 215
      c.save()
      c.lineWidth = 5
      c.globalAlpha = visible * 0.62
      c.filter = 'blur(1.5px)'
      colors.forEach((color, i) => {
        c.strokeStyle = `rgb(${color})`
        c.beginPath()
        c.arc(width * 0.42, 268, radius - i * 5, Math.PI * 1.05, Math.PI * 1.95)
        c.stroke()
      })
      c.restore()
    }

    function drawSunOrMoon(c: CanvasRenderingContext2D, clock: number) {
      const { celestial, dayness, sunsetness, nightness } = now_.values
      if (celestial < 0.02) return
      const x = width * 0.64
      const y = 78
      const sunAlpha = celestial * (dayness + sunsetness)
      if (sunAlpha > 0.02) {
        const color = sunsetness > dayness ? '255, 170, 100' : '255, 226, 150'
        c.save()
        c.translate(x, y)
        c.rotate(clock * 0.00005)
        c.fillStyle = `rgba(${color}, ${0.07 * sunAlpha})`
        for (let i = 0; i < 10; i++) {
          c.rotate((Math.PI * 2) / 10)
          c.beginPath()
          c.moveTo(0, 0)
          c.lineTo(-16, -150)
          c.lineTo(16, -150)
          c.closePath()
          c.fill()
        }
        c.restore()
        const glow = c.createRadialGradient(x, y, 8, x, y, 110)
        glow.addColorStop(0, `rgba(${color}, ${0.75 * sunAlpha})`)
        glow.addColorStop(1, `rgba(${color}, 0)`)
        c.fillStyle = glow
        c.beginPath()
        c.arc(x, y, 110, 0, Math.PI * 2)
        c.fill()
        // Squared: behind thin cloud the sun should read as a glow, not a pale disc.
        c.fillStyle = `rgba(255, 246, 220, ${sunAlpha * sunAlpha})`
        c.beginPath()
        c.arc(x, y, 24, 0, Math.PI * 2)
        c.fill()
      }
      const moonAlpha = celestial * nightness
      if (moonAlpha > 0.02) {
        const halo = c.createRadialGradient(x, y, 12, x, y, 90)
        halo.addColorStop(0, `rgba(190, 210, 255, ${0.4 * moonAlpha})`)
        halo.addColorStop(1, 'rgba(190, 210, 255, 0)')
        c.fillStyle = halo
        c.beginPath()
        c.arc(x, y, 90, 0, Math.PI * 2)
        c.fill()
        c.fillStyle = `rgba(240, 243, 255, ${moonAlpha * moonAlpha})`
        c.beginPath()
        c.arc(x, y, 21, 0, Math.PI * 2)
        c.fill()
        c.fillStyle = `rgba(190, 200, 225, ${0.55 * moonAlpha})`
        for (const [dx, dy, size] of [[-7, -5, 4.5], [6, 3, 3.2], [-2, 9, 2.6], [8, -9, 2]]) {
          c.beginPath()
          c.arc(x + dx, y + dy, size, 0, Math.PI * 2)
          c.fill()
        }
      }
    }

    function drawClouds(c: CanvasRenderingContext2D, elapsed: number) {
      const { cover, shade, wind } = now_.values
      const spriteWidth = width * layers.cloudSize
      const spriteHeight = spriteWidth * (230 / 520)
      const band = variant === 'hero' ? 0.26 : 0.42
      clouds.forEach((cloud, i) => {
        cloud.x += (elapsed * (0.006 + wind * 0.05) * cloud.depth) / Math.max(layers.cloudSize, 0.2)
        if (cloud.x > 1.25) cloud.x = -0.45
        const appear = Math.max(0, Math.min(1, cover * CLOUD_COUNT - i))
        if (appear <= 0) return
        const w = spriteWidth * cloud.depth
        const h = spriteHeight * cloud.depth
        const x = cloud.x * width - w / 2
        const y = cloud.y * height * band - h * 0.3
        c.globalAlpha = appear * (1 - shade) * 0.92
        if (c.globalAlpha > 0.01) c.drawImage(lightCloudsRef.current[cloud.sprite], x, y, w, h)
        c.globalAlpha = appear * shade * 0.95
        if (c.globalAlpha > 0.01) c.drawImage(dark[cloud.sprite], x, y, w, h)
      })
      c.globalAlpha = 1
    }

    function drawFog(c: CanvasRenderingContext2D, clock: number) {
      const fog = now_.values.fog
      if (fog < 0.02) return
      for (let i = 0; i < 3; i++) {
        const y = height * (0.35 + i * 0.25) + Math.sin(clock * 0.00022 + i * 2) * height * 0.05
        const size = height * 0.26
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
      for (const weight of [1, 1.5]) {
        c.strokeStyle = `rgba(210, 228, 255, ${(0.3 + rain * 0.34) * layers.rainAlpha * (weight > 1 ? 1 : 0.8)})`
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
      const { index, power } = strikeAt(clock)
      if (power <= 0) return
      c.fillStyle = `rgba(205, 218, 255, ${layers.flash * power})`
      c.fillRect(0, 0, width, height)
      if (layers.bolts) drawBolt(c, index, power, width, height)
    }

    function draw(clock: number, elapsed: number) {
      if (!context) return
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      context.clearRect(0, 0, width, height)
      if (layers.sky) drawSky(context)
      if (layers.stars) drawStars(context, clock)
      if (layers.celestial) {
        drawRainbow(context)
        drawSunOrMoon(context, clock)
      }
      if (layers.clouds) drawClouds(context, elapsed)
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
