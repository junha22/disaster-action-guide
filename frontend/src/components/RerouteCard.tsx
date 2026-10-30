import { useEffect, useState, type Ref } from 'react'
import { CloudRainWind, Loader2, Sparkles } from 'lucide-react'

import { api } from '@/lib/api'
import { formatDuration, signed } from '@/lib/format'
import { rerouteExplainBody } from '@/lib/reroute'
import type { RainState, RerouteExplainResult, RerouteResult, RerouteSide } from '@/lib/types'

// The explanation is read aloud when it arrives, but the driver is not kept waiting for a slow one.
const VOICE_WAIT_MS = 4000
const ASK = '경로를 변경할까요?'

interface Props {
  decision: RerouteResult
  previous: RainState
  cardRef: Ref<HTMLElement>
  onSpeak: (text: string) => void
  onAccept: () => void
  onDecline: () => void
}

function ZoneCount({ count }: { count: number }) {
  return <strong className={count > 0 ? 'reroute-count-warn' : 'reroute-count-clear'}>{count}곳</strong>
}

function SideColumn({ title, side, dot, added }: { title: string; side: RerouteSide; dot: string; added?: number }) {
  const others = side.zones.length - side.hard_zone_ids.length - side.soft_zone_ids.length
  return (
    <div className="reroute-side">
      <h3><span className={`reroute-dot ${dot}`} aria-hidden="true" />{title}</h3>
      <dl>
        <div><dt>반드시 피할 구간</dt><dd><ZoneCount count={side.hard_zone_ids.length} /></dd></div>
        <div><dt>되도록 피할 구간</dt><dd><ZoneCount count={side.soft_zone_ids.length} /></dd></div>
        {others > 0 && <div><dt>그 밖의 위험 구간</dt><dd>{others}곳</dd></div>}
        <div>
          <dt>남은 시간</dt>
          <dd>{formatDuration(side.duration_s)}{added !== undefined && <small> ({signed(added, formatDuration)})</small>}</dd>
        </div>
      </dl>
    </div>
  )
}

// Asks the driver. The route logic has already decided what to offer; AI only words the reason,
// and the computed template is on screen from the start.
export default function RerouteCard({ decision, previous, cardRef, onSpeak, onAccept, onDecline }: Props) {
  const [explained, setExplained] = useState<RerouteExplainResult | null>(null)
  const [pending, setPending] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    let spoken = false
    const speakOnce = (text: string) => {
      if (spoken) return
      spoken = true
      onSpeak(`${text} ${ASK}`)
    }
    const timer = window.setTimeout(() => speakOnce(decision.text), VOICE_WAIT_MS)
    api.explainReroute(rerouteExplainBody(decision, previous), controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        setExplained(data)
        speakOnce(data.text)
      })
      .catch(() => {
        if (!controller.signal.aborted) speakOnce(decision.text)
      })
      .finally(() => {
        window.clearTimeout(timer)
        if (!controller.signal.aborted) setPending(false)
      })
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [decision, previous, onSpeak])

  const ai = explained?.source === 'ai'
  const added = decision.candidate.duration_s - decision.current.duration_s
  const demo = decision.weather.source === 'demo'

  return (
    <section ref={cardRef} className="reroute-card drive-glass" role="alertdialog" aria-labelledby="reroute-title"
      aria-describedby="reroute-reason" data-testid="reroute-card">
      <header className="reroute-head">
        <span className="reroute-head-icon"><CloudRainWind /></span>
        <div className="min-w-0">
          <h2 id="reroute-title">비가 강해져 경로 변경을 요청해요</h2>
          <p>
            강수 {decision.previous_level}단계 → {decision.weather.level}단계
            {demo && <span className="reroute-demo">시연 값 · 실제 기상 아님</span>}
          </p>
        </div>
      </header>

      <div className="reroute-compare">
        <SideColumn title="현재 경로" side={decision.current} dot="reroute-dot-current" />
        <SideColumn title="변경 경로" side={decision.candidate} dot="reroute-dot-new" added={added} />
      </div>

      <div className="reroute-reason" data-testid="reroute-explanation" data-source={explained?.source ?? ''}>
        <p className="reroute-reason-label">
          <Sparkles />{ai ? 'AI 설명' : '변경 이유'}
          {pending && <Loader2 className="animate-spin" aria-label="설명을 다듬는 중" />}
        </p>
        <p id="reroute-reason" aria-live="polite">{explained?.text ?? decision.text}</p>
      </div>

      <div className="reroute-actions">
        <button type="button" className="reroute-accept" autoFocus onClick={onAccept}>경로 변경</button>
        <button type="button" className="reroute-decline" onClick={onDecline}>현재 경로 유지</button>
      </div>
      <p className="reroute-note">시연 주행은 선택할 때까지 멈춥니다. 실제 침수 여부는 확인하지 않습니다.</p>
    </section>
  )
}
