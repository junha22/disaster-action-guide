import { AlertTriangle, CheckCircle2, Loader2, Navigation, ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { formatDistance, formatDuration, signed } from '@/lib/format'
import type { AppConfig, RouteResult, StrategyInfo, ZoneType } from '@/lib/types'

interface Props {
  config: AppConfig | null
  strategies: StrategyInfo[]
  strategy: string
  onStrategyChange: (name: string) => void
  canSubmit: boolean
  busy: boolean
  onSubmit: () => void
  result: RouteResult | null
  error: string
  showBaseline: boolean
  onShowBaselineChange: (on: boolean) => void
}

function weatherBadge(result: RouteResult) {
  const w = result.weather
  if (w.source === 'demo') return <Badge variant="outline" className="border-orange-400 text-orange-700">데모 값 · 실제 기상 아님</Badge>
  if (w.source === 'unavailable') return <Badge variant="outline" className="border-orange-400 text-orange-700">실제 강수 미반영</Badge>
  return <Badge variant="secondary">기상청</Badge>
}

function ZoneChip({ type, name, config }: { type: ZoneType; name: string; config: AppConfig | null }) {
  const info = config?.zone_types[type]
  return (
    <li className="flex items-center gap-2 text-sm">
      <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: info?.color }} />
      <span className="truncate">{name}</span>
      <span className="shrink-0 text-xs text-muted-foreground">{info?.label ?? type}</span>
    </li>
  )
}

export default function RoutePanel(props: Props) {
  const { config, strategies, strategy, onStrategyChange, canSubmit, busy, onSubmit, result, error, showBaseline,
    onShowBaselineChange } = props
  const current = strategies.find(s => s.name === strategy)
  const e = result?.explanation
  const failed = e?.status === 'avoid_failed'

  return (
    <section className="space-y-3" aria-labelledby="route-title">
      <h2 id="route-title" className="flex items-center gap-2 text-sm font-semibold">
        <Navigation className="size-4" />경로 찾기
      </h2>
      <div className="space-y-1.5">
        <Label htmlFor="strategy">알고리즘</Label>
        <select id="strategy" value={strategy} onChange={event => onStrategyChange(event.target.value)}
          disabled={busy} className="w-full rounded-lg border bg-background px-2.5 py-1.5 text-sm">
          {strategies.map(s => <option key={s.name} value={s.name}>{s.label}{s.default ? ' (기본)' : ''}</option>)}
        </select>
        {current && <p className="text-xs text-muted-foreground">{current.description}</p>}
      </div>
      <Button type="button" className="w-full" size="lg" disabled={!canSubmit || busy} onClick={onSubmit}>
        {busy ? <Loader2 className="animate-spin" /> : <Navigation />}
        {busy ? '경로 계산 중…' : '경로 찾기'}
      </Button>
      {!canSubmit && !busy && <p className="text-xs text-muted-foreground">출발지와 목적지를 모두 정하세요.</p>}
      {error && (
        <p role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}

      {result && e && (
        <div className="space-y-3" data-testid="route-result" data-status={e.status} data-level={e.level}>
          {failed && (
            <div role="alert" className="space-y-1.5 rounded-lg border border-destructive/60 bg-destructive/10 p-3 text-sm">
              <p className="flex items-center gap-2 font-semibold text-destructive">
                <ShieldAlert className="size-4" />{e.warning}
              </p>
              {e.failure_reason && <p>이유: {e.failure_reason}</p>}
              <p className="text-xs">아래 경로는 회피하지 못한 기본 경로입니다. 안전한 경로가 아닙니다.</p>
            </div>
          )}

          <div className="rounded-lg border p-3">
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <Badge>{result.strategy.label}</Badge>
              <Badge variant="outline">강수 단계 {result.weather.level} · {result.weather.rn1_mm}mm</Badge>
              {weatherBadge(result)}
            </div>
            <dl className="grid grid-cols-2 gap-y-1 text-sm">
              <dt className="text-muted-foreground">총 거리</dt>
              <dd className="font-medium">{formatDistance(result.metrics.route.distance_m)}</dd>
              <dt className="text-muted-foreground">예상 소요시간</dt>
              <dd className="font-medium">{formatDuration(result.metrics.route.duration_s)}</dd>
            </dl>
          </div>

          <div className="space-y-2 rounded-lg border p-3" aria-label="회피 근거">
            <p className="flex items-center gap-2 text-sm font-medium">
              {failed ? <AlertTriangle className="size-4 text-destructive" /> : <CheckCircle2 className="size-4 text-green-600" />}
              {e.message}
            </p>
            {e.avoided_zones.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">피한 위험 구역</p>
                <ul className="space-y-1">
                  {e.avoided_zones.map(z => <ZoneChip key={z.id} type={z.type} name={z.name} config={config} />)}
                </ul>
              </div>
            )}
            {e.passed_zones.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {failed ? '이 경로가 지나는 위험 구역' : '경로가 지나는 위험 구역'}
                </p>
                <ul className="space-y-1">
                  {e.passed_zones.map(z => (
                    <ZoneChip key={z.id} type={z.type} name={`${z.name} · ${Math.round(z.length_m)}m`} config={config} />
                  ))}
                </ul>
              </div>
            )}
            <dl className="grid grid-cols-2 gap-y-1 border-t pt-2 text-sm">
              <dt className="text-muted-foreground">baseline 대비 소요시간</dt>
              <dd>{signed(e.added_duration_s, formatDuration)}</dd>
              <dt className="text-muted-foreground">baseline 대비 거리</dt>
              <dd>{signed(e.added_distance_m, formatDistance)}</dd>
              <dt className="text-muted-foreground">위험 노출 점수</dt>
              <dd>
                {Math.round(result.metrics.baseline.exposure_score)} → <strong>{Math.round(result.metrics.route.exposure_score)}</strong>
              </dd>
            </dl>
          </div>

          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="show-baseline">baseline 경로(회색 점선) 보기</Label>
            <Switch id="show-baseline" checked={showBaseline} onCheckedChange={onShowBaselineChange} />
          </div>

          {result.metrics.alternatives.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">다른 후보 경로 (지도에 연보라색)</p>
              <ul className="space-y-0.5 text-xs">
                {result.metrics.alternatives.map((m, i) => (
                  <li key={i} className="flex justify-between gap-2">
                    <span className="truncate">{m.label}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {formatDuration(m.duration_s)} · 노출 {Math.round(m.exposure_score)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
