import { CloudRain, Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { formatObserved } from '@/lib/format'
import { ALERT_LABELS, avoidTypesFor, rainLevel } from '@/lib/level'
import type { Alert, AppConfig, WeatherInfo } from '@/lib/types'

interface Props {
  config: AppConfig | null
  weather: WeatherInfo | null
  loading: boolean
  demoMode: boolean
  onDemoModeChange: (on: boolean) => void
  rain: number
  onRainChange: (value: number) => void
  onRainCommit: (value: number) => void
  alert: Alert
  onAlertChange: (alert: Alert) => void
}

const ALERTS: Alert[] = ['none', 'advisory', 'warning']

export default function WeatherPanel(props: Props) {
  const { config, weather, loading, demoMode, onDemoModeChange, rain, onRainChange, onRainCommit, alert,
    onAlertChange } = props
  const rules = config?.level_rules
  const available = Boolean(weather?.available)
  const level = rules
    ? demoMode ? rainLevel(rain, alert, rules) : (available ? weather?.level ?? 0 : 0)
    : null
  const avoid = rules && level !== null ? avoidTypesFor(level, rules) : []
  const avoidText = avoid.length ? avoid.map(t => config?.zone_types[t].label).join(', ') : '없음'

  return (
    <section className="space-y-3" aria-labelledby="weather-title">
      <div className="flex items-center justify-between gap-2">
        <h2 id="weather-title" className="flex items-center gap-2 text-sm font-semibold">
          <CloudRain className="size-4" />기상 정보
        </h2>
        {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="불러오는 중" />}
      </div>

      {!loading && (available ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg border p-3 text-sm">
          <dt className="text-muted-foreground">시간당 강수량</dt><dd>{weather?.rn1_mm} mm</dd>
          <dt className="text-muted-foreground">호우 특보</dt><dd>{weather?.alert_label}</dd>
          <dt className="text-muted-foreground">강수 단계</dt><dd>{weather?.level ?? '-'}단계</dd>
          <dt className="text-muted-foreground">기준 시각</dt><dd>{formatObserved(weather?.observed_at ?? null)}</dd>
          <dt className="text-muted-foreground">출처</dt><dd>기상청</dd>
        </dl>
      ) : (
        <p role="status" className="rounded-lg border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
          {weather?.message ?? '기상 정보를 가져오지 못했습니다'}. 데모 모드로 계산합니다.
        </p>
      ))}

      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="demo-mode">데모 모드 (강수량 직접 지정)</Label>
        <Switch id="demo-mode" checked={demoMode} disabled={!available}
          onCheckedChange={checked => onDemoModeChange(checked)} />
      </div>

      {demoMode && (
        <div className="space-y-3 rounded-lg border border-dashed p-3">
          <Badge variant="outline" className="border-orange-400 text-orange-700">데모 값 · 실제 기상 아님</Badge>
          <div className="space-y-2">
            <div className="flex items-baseline justify-between text-sm">
              <Label htmlFor="demo-rain">시간당 강수량</Label>
              <span className="font-semibold tabular-nums" aria-live="polite">{rain} mm</span>
            </div>
            <Slider id="demo-rain" min={0} max={100} step={5} value={[rain]} thumbLabel="시간당 강수량(mm)"
              onValueChange={values => onRainChange(values[0])}
              onValueCommit={values => onRainCommit(values[0])} />
          </div>
          <div className="space-y-1.5">
            <p className="text-sm font-medium">호우 특보</p>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="호우 특보">
              {ALERTS.map(a => (
                <Button key={a} type="button" size="sm" role="radio" aria-checked={alert === a}
                  variant={alert === a ? 'default' : 'outline'} onClick={() => onAlertChange(a)}>
                  {ALERT_LABELS[a]}
                </Button>
              ))}
            </div>
          </div>
        </div>
      )}

      {level !== null && (
        <p className="text-sm">
          <span className="font-semibold">강수 단계 {level}</span>
          <span className="text-muted-foreground"> · 피하는 구역: {avoidText}</span>
        </p>
      )}
    </section>
  )
}
