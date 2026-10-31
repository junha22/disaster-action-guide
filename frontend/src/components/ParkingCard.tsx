import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Car, CheckCircle2, HelpCircle, Loader2, MapPin, Play, Volume2, VolumeX } from 'lucide-react'

import SearchBar from '@/components/SearchBar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/lib/api'
import { formatObserved } from '@/lib/format'
import { speak, speechSupported, stopSpeaking } from '@/lib/speech'
import type { ParkingCheck, Place } from '@/lib/types'

interface Props {
  demoPoints: Place[]
  bbox: [number, number, number, number] | null
}

const STORAGE_KEY = 'parked-car'
const REFRESH_MS = 5 * 60 * 1000
const DEMO_ID = 'parking-demo'
// The sample place in the data notes: a frequently flooded zone in Mangwol-dong.
const DEMO_PLACE: Place = {
  id: DEMO_ID, name: '시연 위치 · 망월동', address: '', lon: 126.9558918, lat: 35.2047702, selectable: true, reason: null, source: 'demo',
}

type Verdict = 'unknown' | 'none' | 'soon' | 'reached'
const SEVERITY: Record<Verdict, number> = { unknown: 0, none: 0, soon: 1, reached: 2 }

function verdictOf(check: ParkingCheck): Verdict {
  if (!check.rain) return 'unknown'
  if (check.rain.minutes === null) return 'none'
  return check.rain.minutes === 0 ? 'reached' : 'soon'
}

// The position stays on this device: storage may be blocked, and the card works without it.
function readSaved(): Place | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as Partial<Place>
    if (typeof saved.lon !== 'number' || typeof saved.lat !== 'number' || typeof saved.name !== 'string') return null
    return { id: saved.id ?? 'parked', name: saved.name, address: saved.address ?? '', lon: saved.lon, lat: saved.lat,
      selectable: true, reason: null, source: saved.source ?? 'gps' }
  } catch {
    return null
  }
}

function writeSaved(place: Place | null) {
  try {
    if (place) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(place))
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Kept for this visit only.
  }
}

function minutesText(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (!h) return `${m}분`
  return m ? `${h}시간 ${m}분` : `${h}시간`
}

function spokenAlert(verdict: Verdict, minutes: number | null): string {
  if (verdict === 'reached') return '주차한 곳의 비가 과거 침수일 기준에 도달했어요. 차를 옮길지 확인하세요.'
  return `약 ${minutesText(minutes ?? 0)} 뒤 과거 침수일 기준에 도달할 수 있어요. 차를 옮길지 확인하세요.`
}

function ZoneLine({ check }: { check: ParkingCheck }) {
  const zone = check.zone
  if (!zone) return <p className="text-sm">기록된 침수 구역 밖이에요. 안전하다는 뜻은 아니에요.</p>
  if (zone.kind === 'service_records') {
    return <p className="text-sm">침수 기록이 있는 곳이에요 · <span className="text-muted-foreground">{zone.name}</span></p>
  }
  return (
    <p className="text-sm">
      {zone.name} <strong>{zone.grade} 구역</strong>
      <span className="text-muted-foreground"> · 2021~2023년 기록 {zone.records}건, 최근 {zone.flood_dates.at(-1)}</span>
    </p>
  )
}

function VerdictBox({ check }: { check: ParkingCheck }) {
  const verdict = verdictOf(check)
  const rain = check.rain
  if (verdict === 'unknown' || !rain) {
    return (
      <div role="status" className="flex gap-2 rounded-lg border border-amber-300/60 bg-amber-400/15 px-2.5 py-2 text-xs leading-5"
        data-testid="parking-verdict" data-verdict="unknown">
        <HelpCircle className="mt-0.5 size-4 shrink-0 text-amber-200" />
        강수 자료를 받지 못해 판단하지 못했어요. 안전하다는 뜻이 아니에요. 기상청 예보와 재난문자를 확인하세요.
      </div>
    )
  }
  const box = verdict === 'reached' ? 'border-red-400/50 bg-red-500/15'
    : verdict === 'soon' ? 'border-amber-300/60 bg-amber-400/15' : 'border-white/15 bg-white/5'
  return (
    <div role={verdict === 'none' ? 'status' : 'alert'} className={`space-y-1 rounded-lg border px-2.5 py-2 ${box}`} data-testid="parking-verdict" data-verdict={verdict}>
      <p className="flex items-center gap-2 text-[15px] font-semibold">
        {verdict === 'reached' && <><AlertTriangle className="size-[18px] shrink-0 text-red-400" />과거 침수일 비 기준에 도달했어요</>}
        {verdict === 'soon' && <><AlertTriangle className="size-[18px] shrink-0 text-amber-300" />기준 도달까지 약 {minutesText(rain.minutes ?? 0)}</>}
        {verdict === 'none' && <><CheckCircle2 className="size-[18px] shrink-0 text-emerald-400" />{check.forecast_ok ? `앞으로 ${rain.forecast_hours}시간 안에 기준에 닿지 않아요` : '지금까지 온 비는 기준 아래예요'}</>}
      </p>
      {verdict !== 'none' && <p className="text-sm">차를 옮길지 확인하세요.</p>}
      <p className="text-xs leading-5 text-muted-foreground">
        최근 3시간 {rain.sum_3h}mm · 24시간 {rain.sum_24h}mm · 기준 3시간 {rain.need_3h}mm
        (24시간 {rain.wet_24h}mm 이상이면 {rain.wet_3h}mm)
        {check.observed_at && ` · ${formatObserved(check.observed_at)} 기준`}
      </p>
      {!check.forecast_ok && <p className="text-xs leading-5 text-amber-200">예보를 받지 못해 지금까지 온 비로만 봤어요.</p>}
      {check.missing_hours > 0 && <p className="text-xs leading-5 text-amber-200">관측값 {check.missing_hours}시간이 비어 있어 비가 없던 것으로 계산했어요.</p>}
    </div>
  )
}

// Works on its own: it shares no state with the route, the map or the weather card.
export default function ParkingCard({ demoPoints, bbox }: Props) {
  const [parked, setParked] = useState<Place | null>(readSaved)
  const [open, setOpen] = useState(() => parked !== null)
  const [check, setCheck] = useState<ParkingCheck | null>(null)
  const [error, setError] = useState('')
  const [voice, setVoice] = useState(true)
  const voiceOn = useRef(true)
  const spoken = useRef(0)
  const demo = parked?.id === DEMO_ID
  const checking = Boolean(parked && !check && !error)

  useEffect(() => {
    if (!parked) return
    let current: AbortController | null = null
    const read = () => {
      current?.abort()
      const controller = new AbortController()
      current = controller
      api.parkingCheck({ lon: parked.lon, lat: parked.lat, demo: parked.id === DEMO_ID }, controller.signal)
        .then(data => {
          setCheck(data)
          setError('')
          const verdict = verdictOf(data)
          // Each step up is said once. The same state does not repeat every five minutes.
          // Queued, not interrupting: this runs on a timer and must not cut off anything else being read.
          if (SEVERITY[verdict] > spoken.current) {
            spoken.current = SEVERITY[verdict]
            if (voiceOn.current) speak(spokenAlert(verdict, data.rain?.minutes ?? null))
          }
        })
        .catch(e => {
          if (controller.signal.aborted) return
          // A failed refresh keeps the last answer on screen, with the failure next to it.
          setError(errorMessage(e, '주차 위치를 확인하지 못했어요.'))
        })
    }
    read()
    // The demo's rain never changes.
    const timer = parked.id === DEMO_ID ? undefined : window.setInterval(read, REFRESH_MS)
    return () => {
      window.clearInterval(timer)
      current?.abort()
    }
  }, [parked])

  function changeParked(place: Place | null) {
    spoken.current = 0
    setCheck(null)
    setError('')
    setParked(place)
  }

  function choosePlace(place: Place | null) {
    writeSaved(place)
    if (!place) stopSpeaking()
    changeParked(place)
  }

  return (
    <section className="glass-card space-y-2.5" aria-label="주차한 차 확인" data-testid="parking-card">
      <div className="flex items-start gap-2">
        <Car className="mt-0.5 size-[18px] shrink-0" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] leading-snug font-semibold">주차한 차 확인</h2>
          {!parked && <p className="mt-0.5 text-xs leading-5 text-muted-foreground">비가 과거 침수일 수준에 닿기까지 몇 분 남았는지 알려드려요.</p>}
        </div>
        {parked && speechSupported() && (
          <Button type="button" variant="ghost" size="icon-sm" aria-pressed={voice} aria-label={voice ? '음성 알림 끄기' : '음성 알림 켜기'}
            onClick={() => {
              if (voice) stopSpeaking()
              voiceOn.current = !voice
              setVoice(!voice)
            }}>
            {voice ? <Volume2 /> : <VolumeX />}
          </Button>
        )}
      </div>

      {!open && !parked && (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={() => setOpen(true)}><MapPin />주차 위치 정하기</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => changeParked(DEMO_PLACE)}><Play />시연 보기</Button>
        </div>
      )}

      {(open || parked) && (
        <SearchBar id="parking" label="주차 위치" value={parked} onChange={choosePlace} demoPoints={demoPoints} bbox={bbox} allowCurrentLocation />
      )}

      {checking && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />확인 중…</p>}
      {error && <p role="alert" className="text-xs leading-5 text-amber-200">{check ? '다시 확인하지 못해 이전 결과를 보여줘요. ' : ''}{error}</p>}

      {check && (
        <>
          {check.demo && <Badge variant="outline" className="border-amber-300/60 text-amber-200">시연 값 · 실제 기상 아님</Badge>}
          <ZoneLine check={check} />
          <VerdictBox check={check} />
          <p className="text-xs leading-5 text-muted-foreground">
            과거 침수일의 비로 만든 기준이고 실제 침수 여부는 확인하지 않아요. 남은 시간은 시간별 예보로 어림한 값이에요.
            {!demo && ' 이 화면을 열어 둔 동안 5분마다 다시 확인하고, 닫으면 알리지 못해요. 주차 위치는 이 기기에만 저장해요.'}
          </p>
        </>
      )}
    </section>
  )
}
