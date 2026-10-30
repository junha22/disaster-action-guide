import { Loader2, Navigation } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface Props {
  canSubmit: boolean
  busy: boolean
  onSubmit: () => void
  error: string
}

export default function RoutePanel({ canSubmit, busy, onSubmit, error }: Props) {
  return (
    <section className="space-y-3" aria-label="경로 찾기">
      <Button type="button" className="btn-route w-full" size="lg" disabled={!canSubmit || busy} onClick={onSubmit}>
        {busy ? <Loader2 className="animate-spin" /> : <Navigation />}
        {busy ? '경로 계산 중…' : '경로 찾기'}
      </Button>
      {!canSubmit && !busy && <div className="text-xs text-muted-foreground">출발지와 목적지를 모두 정하세요.</div>}
      {error && (
        <p role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
    </section>
  )
}
