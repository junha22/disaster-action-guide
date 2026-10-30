import { Info, Loader2, MapPin, Moon, Sun, Sunset, Umbrella } from 'lucide-react'

import WeatherCanvas from '@/components/WeatherCanvas'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { formatObserved } from '@/lib/format'
import { ALERT_LABELS, avoidRuleText, rainLevel } from '@/lib/level'
import type { SceneSpec, TimeOfDay } from '@/lib/scene'
import type { Alert, AppConfig, WeatherInfo } from '@/lib/types'

interface Props {
  config: AppConfig | null
  weather: WeatherInfo | null
  loading: boolean
  scene: SceneSpec
  dummyZonesNotice: string
  timeChoice: TimeOfDay | null
  onTimeChoiceChange: (time: TimeOfDay | null) => void
  rainShown: number
  demoMode: boolean
  onDemoModeChange: (on: boolean) => void
  rain: number
  onRainChange: (value: number) => void
  onRainCommit: (value: number) => void
  alert: Alert
  onAlertChange: (alert: Alert) => void
}

const ALERTS: Alert[] = ['none', 'advisory', 'warning']
// One example value inside each rain level, for jumping between levels during a demo.
const LEVEL_PRESETS = [0, 35, 55, 75]
const TIMES: { time: TimeOfDay; label: string; Icon: typeof Sun }[] = [
  { time: 'day', label: '낮', Icon: Sun },
  { time: 'sunset', label: '노을', Icon: Sunset },
  { time: 'night', label: '밤', Icon: Moon },
]

export default function WeatherPanel(props: Props) {
  const { config, weather, loading, scene, dummyZonesNotice, timeChoice, onTimeChoiceChange, rainShown, demoMode,
    onDemoModeChange, rain, onRainChange, onRainCommit, alert, onAlertChange } = props
  const rules = config?.level_rules
  const available = Boolean(weather?.available)
  const level = rules
    ? demoMode ? rainLevel(rain, alert, rules) : (available ? weather?.level ?? 0 : 0)
    : null
  // e.g. "지하차도(반드시), 침수 이력 우선 회피(되도록)" (design.md 5.8)
  const avoidText = config && level !== null ? avoidRuleText(level, config) : '없음'
  const activeAlert = demoMode ? alert : weather?.alert ?? 'none'

  return (
    <section className="weather-hero" aria-labelledby="weather-title" data-kind={scene.kind} data-time={scene.time}>
      <WeatherCanvas spec={scene} variant="hero" />
      <div className="hero-scrim" aria-hidden="true" />

      <div className="relative">
        <div className="flex items-center justify-between gap-2">
          <h1 className="flex items-center gap-2 font-bold">
            <Umbrella className="size-5" />호우 안전 경로 · 광주
          </h1>
          <div className="time-switch" role="group" aria-label="배경 시간대 (장식용, 경로에 영향 없음)">
            {TIMES.map(({ time, label, Icon }) => (
              <button key={time} type="button" aria-label={label} title={`${label} 배경으로 보기`}
                aria-pressed={timeChoice === time} onClick={() => onTimeChoiceChange(timeChoice === time ? null : time)}>
                <Icon className="size-3.5" />
              </button>
            ))}
          </div>
        </div>

        <div className="mt-16 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span className="flex items-center gap-1 text-white/90"><MapPin className="size-3.5" />광주광역시</span>
          {loading && <Loader2 className="size-4 animate-spin text-white/80" aria-label="불러오는 중" />}
          {!loading && (demoMode
            ? <span className="demo-pill">데모 값 · 실제 기상 아님</span>
            : <span className="text-white/80">기상청 · {formatObserved(weather?.observed_at ?? null)}</span>)}
          {dummyZonesNotice && <Badge variant="outline" className="demo-pill !h-auto font-normal">{dummyZonesNotice}</Badge>}
        </div>

        <div className="mt-1 flex items-end justify-between gap-3">
          <h2 id="weather-title" className="weather-title">{scene.title}</h2>
          <p className="shrink-0 text-right leading-none" aria-live="polite">
            <span className="weather-number">{rainShown}</span>
            <span className="ml-1 text-sm text-white/85">mm/h</span>
          </p>
        </div>

        {level !== null && (
          <p className="mt-2 text-sm text-white/95">
            <strong>강수 {level}단계</strong> · 피하는 구역: {avoidText}
            {activeAlert !== 'none' && <strong className="ml-1.5 text-amber-300">{ALERT_LABELS[activeAlert]}</strong>}
          </p>
        )}

        {!loading && available && !demoMode && (
          <p className={`mt-1.5 text-xs ${weather?.alert_status === 'failed' ? 'font-medium text-amber-200' : 'text-white/85'}`}>
            호우 특보: {weather?.alert_label}
          </p>
        )}

        {!loading && !available && (
          <p role="status" className="mt-1.5 flex gap-1.5 text-xs text-white/85">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            {weather?.message ?? '기상 정보를 가져오지 못했습니다'}. 데모 모드로 계산합니다.
          </p>
        )}

        {available && (
          <div className="mt-3 flex items-center justify-between gap-2">
            <Label htmlFor="demo-mode" className="text-white/95">데모 모드 (강수량 직접 지정)</Label>
            <Switch id="demo-mode" checked={demoMode} onCheckedChange={checked => onDemoModeChange(checked)} />
          </div>
        )}

        {demoMode && (
          <div className="mt-3 space-y-3">
            <div className="grid grid-cols-4 gap-1.5" role="group" aria-label="강수 단계 바로 고르기">
              {LEVEL_PRESETS.map((value, index) => (
                <button key={value} type="button" className="level-chip" aria-pressed={level === index}
                  onClick={() => onRainCommit(value)}>
                  <span className="block text-sm font-semibold tabular-nums">{value}mm</span>
                  <span className="block text-[11px] opacity-85">{index}단계</span>
                </button>
              ))}
            </div>
            <div className="space-y-2">
              <Label htmlFor="demo-rain" className="text-white/95">시간당 강수량</Label>
              <Slider id="demo-rain" min={0} max={100} step={5} value={[rain]} thumbLabel="시간당 강수량(mm)"
                onValueChange={values => onRainChange(values[0])}
                onValueCommit={values => onRainCommit(values[0])} />
            </div>
            <div className="flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="호우 특보">
              <span className="mr-1 text-sm font-medium text-white/95">호우 특보</span>
              {ALERTS.map(a => (
                <Button key={a} type="button" size="sm" role="radio" aria-checked={alert === a}
                  variant={alert === a ? 'default' : 'outline'} onClick={() => onAlertChange(a)}>
                  {ALERT_LABELS[a]}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
