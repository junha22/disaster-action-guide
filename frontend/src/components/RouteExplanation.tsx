import { useEffect, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'

import { api } from '@/lib/api'
import { explainBody, needsExplanation } from '@/lib/explain'
import type { RouteExplainResult, RouteResult } from '@/lib/types'

type State = { kind: 'loading' } | { kind: 'done'; data: RouteExplainResult } | { kind: 'error' }

// Requirement 8: sentences under the route card. Fetched after the route is shown, so the
// route result never waits for the LLM. On a network error the block is simply hidden.
export default function RouteExplanation({ result }: { result: RouteResult }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const wanted = needsExplanation(result)

  useEffect(() => {
    if (!wanted) return
    const controller = new AbortController()
    api.explainRoute(explainBody(result), controller.signal)
      .then(data => setState({ kind: 'done', data }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [result, wanted])

  if (!wanted || state.kind === 'error') return null
  const ai = state.kind === 'done' && state.data.source === 'ai'
  return (
    <div className="route-explain" aria-label="경로 설명"
      aria-live="polite" data-testid="route-explanation" data-source={state.kind === 'done' ? state.data.source : ''}>
      <p className="route-explain-label">
        <Sparkles className="size-3.5" />{ai ? 'AI 설명' : '경로 설명'}
      </p>
      {state.kind === 'loading' ? (
        <p className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />설명을 만드는 중…
        </p>
      ) : (
        <p>{state.data.text}</p>
      )}
    </div>
  )
}
