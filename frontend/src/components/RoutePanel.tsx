import { Loader2, Navigation } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import type { StrategyInfo } from '@/lib/types'

interface Props {
  strategies: StrategyInfo[]
  strategy: string
  onStrategyChange: (name: string) => void
  canSubmit: boolean
  busy: boolean
  onSubmit: () => void
  error: string
}

export default function RoutePanel(props: Props) {
  const { strategies, strategy, onStrategyChange, canSubmit, busy, onSubmit, error } = props
  const current = strategies.find(s => s.name === strategy)

  return (
    <section className="space-y-3" aria-label="경로 찾기">
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
      <div className="space-y-1.5">
        <Label htmlFor="strategy">알고리즘</Label>
        <select id="strategy" value={strategy} onChange={event => onStrategyChange(event.target.value)}
          disabled={busy} className="w-full rounded-lg border bg-background/60 px-2.5 py-1.5 text-sm">
          {strategies.map(s => <option key={s.name} value={s.name}>{s.label}{s.default ? ' (기본)' : ''}</option>)}
        </select>
        {current && <p className="text-xs text-muted-foreground">{current.description}</p>}
      </div>
    </section>
  )
}
