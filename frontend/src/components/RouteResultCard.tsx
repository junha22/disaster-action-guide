import { AlertTriangle, CheckCircle2, ChevronDown, Loader2, Navigation, ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import RouteExplanation from '@/components/RouteExplanation'
import { formatDistance, formatDuration, signed } from '@/lib/format'
import type { AppConfig, RouteResult, ZoneType } from '@/lib/types'

interface Props {
  config: AppConfig | null
  result: RouteResult
  showBaseline: boolean
  onShowBaselineChange: (on: boolean) => void
  starting: boolean
  onStartDrive: () => void
}

function weatherBadge(result: RouteResult) {
  const w = result.weather
  if (w.source === 'demo') return <Badge variant="outline" className="border-amber-300/60 text-amber-200">데모 값 · 실제 기상 아님</Badge>
  if (w.source === 'unavailable') return <Badge variant="outline" className="border-amber-300/60 text-amber-200">실제 강수 미반영</Badge>
  return <Badge variant="secondary">기상청{w.region ? ` · ${w.region} 기준` : ''}</Badge>
}

interface ZoneRow {
  id: string
  name: string
  type: ZoneType
  length_m?: number
}

// Real data can put many zones on one route, so show one line per type and list the names on demand.
function ZoneSummary({ zones, config }: { zones: ZoneRow[]; config: AppConfig | null }) {
  const types = [...new Set(zones.map(z => z.type))]
  return (
    <>
      <ul className="space-y-1">
        {types.map(type => {
          const members = zones.filter(z => z.type === type)
          const metres = members.reduce((sum, z) => sum + (z.length_m ?? 0), 0)
          return (
            <li key={type} className="flex items-center gap-2 text-sm">
              <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: config?.zone_types[type]?.color }} />
              <span>{config?.zone_types[type]?.label ?? type} {members.length}곳</span>
              {metres > 0 && <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{formatDistance(metres)}</span>}
            </li>
          )
        })}
      </ul>
      <details className="group mt-1">
        <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground">
          <ChevronDown className="size-3 transition-transform group-open:rotate-180" />구역 이름 보기
        </summary>
        <ul className="mt-1 space-y-0.5 text-xs">
          {zones.map(z => (
            <li key={z.id} className="flex justify-between gap-2">
              <span>{z.name}</span>
              {z.length_m !== undefined && <span className="shrink-0 tabular-nums text-muted-foreground">{formatDistance(z.length_m)}</span>}
            </li>
          ))}
        </ul>
      </details>
    </>
  )
}

function PassedLine({ label, zones, config }: { label: string; zones: ZoneRow[]; config: AppConfig | null }) {
  const parts = [...new Set(zones.map(z => z.type))].map(type => {
    const count = zones.filter(z => z.type === type).length
    return `${config?.zone_types[type]?.label ?? type} ${count}곳`
  })
  const metres = zones.reduce((sum, z) => sum + (z.length_m ?? 0), 0)
  return (
    <div className="pl-[26px] text-xs font-medium text-amber-200">
      {label}: {parts.join(', ')}{metres > 0 ? ` · ${formatDistance(metres)}` : ''}
    </div>
  )
}

function headline(result: RouteResult, config: AppConfig | null): string {
  const e = result.explanation
  if (e.status === 'avoid_failed') return e.warning ?? e.message
  // With zones still on the route, only the server's tier-level wording is accurate.
  if (e.status !== 'avoided' || e.avoided_zones.length === 0 || e.passed_zones.length > 0) return e.message
  const types = [...new Set(e.avoided_zones.map(z => z.type))]
  return `${types.map(t => config?.zone_types[t].label ?? t).join('·')} 구역을 피했습니다.`
}

function timeNote(addedSeconds: number): string {
  if (Math.round(addedSeconds) === 0) return '가장 빠른 길과 소요시간이 같습니다.'
  const amount = formatDuration(addedSeconds)
  return `가장 빠른 길보다 ${amount} ${addedSeconds > 0 ? '더 걸립니다' : '덜 걸립니다'}.`
}

export default function RouteResultCard({ config, result, showBaseline, onShowBaselineChange, starting, onStartDrive }: Props) {
  const e = result.explanation
  const failed = e.status === 'avoid_failed'
  // Partial avoidance still passes some soft zones: never shown with the "safe" check mark.
  const partial = e.status === 'partially_avoided'
  const avoided = e.avoided_zones.length > 0 && !partial && e.passed_zones.length === 0
  // baseline and rerank have no list of zones to avoid, so their zones cannot be sorted into the two lines.
  const hasRules = e.status !== 'baseline' && e.status !== 'ranked'
  const toAvoid = hasRules ? e.passed_zones.filter(z => e.avoid_groups.includes(z.group)) : e.passed_zones
  const others = hasRules ? e.passed_zones.filter(z => !e.avoid_groups.includes(z.group)) : []
  const scoreRose = result.metrics.route.exposure_score > result.metrics.baseline.exposure_score
  const mustAvoid = (zones: { group: string }[]) => zones.filter(z => e.hard_groups.includes(z.group)).length
  const fewer = mustAvoid(e.baseline_passed_zones) - mustAvoid(e.passed_zones)

  return (
    <div className="space-y-2.5" data-testid="route-result" data-status={e.status} data-level={e.level} aria-live="polite">
      <div>
        <p className="flex items-start gap-2 text-[15px] leading-snug font-semibold">
          {failed
            ? <ShieldAlert className="mt-0.5 size-[18px] shrink-0 text-red-400" />
            : avoided
              ? <CheckCircle2 className="mt-0.5 size-[18px] shrink-0 text-emerald-400" />
              : <AlertTriangle className="mt-0.5 size-[18px] shrink-0 text-amber-300" />}
          {headline(result, config)}
        </p>
        {!failed && <p className="mt-0.5 pl-[26px] text-xs text-muted-foreground">{timeNote(e.added_duration_s)}</p>}
      </div>

      {failed && (
        <div role="alert" className="space-y-0.5 rounded-lg border border-red-400/50 bg-red-500/15 px-2.5 py-2 text-xs leading-5">
          {e.failure_reason && <p className="font-semibold">이유: {e.failure_reason}</p>}
          {fewer > 0 && (
            <p>
              피할 구역을 가장 적게 지나는 경로입니다. 가장 빠른 길보다 {fewer}곳 적게 지나고,
              {Math.round(e.added_duration_s) === 0 ? ' 소요시간은 같습니다.' : ` ${formatDuration(e.added_duration_s)} ${e.added_duration_s > 0 ? '더' : '덜'} 걸립니다.`}
            </p>
          )}
          <p>피할 구역을 모두 피하지 못했습니다. 안전한 경로가 아닙니다.</p>
        </div>
      )}
      {partial && (
        <div role="alert" className="rounded-lg border border-amber-300/60 bg-amber-400/15 px-2.5 py-2 text-xs leading-5">
          <strong>일부 회피</strong> ·{' '}
          {e.clear_option
            ? `모두 피하는 경로는 ${signed(e.clear_option.added_duration_s, formatDuration)}, 거리 ${signed(e.clear_option.added_distance_m, formatDistance)}입니다.`
            : '피할 구역을 모두 피하는 경로를 찾지 못했습니다.'}
        </div>
      )}

      {/* Safety information, so it stays outside the fold whatever else is collapsed. */}
      {toAvoid.length > 0 && <PassedLine label={hasRules ? '지나는 피할 구역' : '지나는 위험 구역'} zones={toAvoid} config={config} />}
      {others.length > 0 && <PassedLine label="이번 단계에서 피하지 않는 위험 구역" zones={others} config={config} />}

      <dl className="grid grid-cols-2 gap-2">
        <div className="stat-tile">
          <dt>예상 소요시간</dt>
          <dd>{formatDuration(result.metrics.route.duration_s)}</dd>
        </div>
        <div className="stat-tile">
          <dt>총 거리</dt>
          <dd>{formatDistance(result.metrics.route.distance_m)}</dd>
        </div>
      </dl>

      <Button type="button" className="btn-route w-full" size="lg" disabled={starting} onClick={onStartDrive}>
        {starting ? <Loader2 className="animate-spin" /> : <Navigation />}
        {starting ? '안내 준비 중…' : '안내 시작 (시연 주행)'}
      </Button>

      <RouteExplanation result={result} />

      <details className="group/more">
        <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-muted-foreground">
          <ChevronDown className="size-3.5 transition-transform group-open/more:rotate-180" />자세히 보기
        </summary>
        <div className="mt-2.5 space-y-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">강수 {result.weather.level}단계</Badge>
            {weatherBadge(result)}
          </div>

          {e.avoided_zones.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">피한 위험 구역</p>
              <ZoneSummary zones={e.avoided_zones} config={config} />
            </div>
          )}
          {e.passed_zones.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-amber-200">이 경로가 지나는 위험 구역</p>
              <ZoneSummary zones={e.passed_zones} config={config} />
            </div>
          )}

          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="show-baseline">가장 빠른 길(점선) 보기</Label>
            <Switch id="show-baseline" checked={showBaseline} onCheckedChange={onShowBaselineChange} />
          </div>

          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">가장 빠른 길 대비 시간</dt>
            <dd className="tabular-nums">{signed(e.added_duration_s, formatDuration)}</dd>
            <dt className="text-muted-foreground">가장 빠른 길 대비 거리</dt>
            <dd className="tabular-nums">{signed(e.added_distance_m, formatDistance)}</dd>
            <dt className="text-muted-foreground">위험 노출 점수</dt>
            <dd className="tabular-nums">
              {Math.round(result.metrics.baseline.exposure_score)} → <strong>{Math.round(result.metrics.route.exposure_score)}</strong>
            </dd>
          </dl>
          {scoreRose && (
            <p className="text-xs text-muted-foreground">
              위험 노출 점수는 구간 길이로 계산해 회피 등급을 반영하지 않습니다. 경로는 등급까지 따져 골랐습니다.
            </p>
          )}

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
      </details>
    </div>
  )
}
