import { useState, type FormEvent } from 'react'
import { Loader2, LocateFixed, Search, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, errorMessage } from '@/lib/api'
import type { Place, SearchResult } from '@/lib/types'

interface Props {
  id: string
  label: string
  value: Place | null
  onChange: (place: Place | null) => void
  demoPoints: Place[]
  bbox: [number, number, number, number] | null
  allowCurrentLocation?: boolean
}

function inBox(lon: number, lat: number, bbox: [number, number, number, number]) {
  return bbox[0] <= lon && lon <= bbox[2] && bbox[1] <= lat && lat <= bbox[3]
}

export default function SearchBar({ id, label, value, onChange, demoPoints, bbox, allowCurrentLocation }: Props) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<SearchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState('')
  const [showDemo, setShowDemo] = useState(false)
  const [locating, setLocating] = useState(false)

  function choose(place: Place) {
    onChange(place)
    setResult(null)
    setShowDemo(false)
    setQuery('')
    setHint('')
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const q = query.trim()
    if (q.length < 2) {  // requirement 1.2: no request under two characters
      setHint('2글자 이상 입력하세요.')
      return
    }
    setBusy(true)
    setHint('')
    try {
      setResult(await api.search(q))
    } catch (e) {
      setResult(null)
      setHint(errorMessage(e, '검색에 실패했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  function currentLocation() {
    // Requirement 1.5: permission is requested only when this button is pressed.
    if (!navigator.geolocation) {
      setHint('이 브라우저에서는 현재 위치를 쓸 수 없습니다. 검색으로 정하세요.')
      return
    }
    setLocating(true)
    setHint('')
    navigator.geolocation.getCurrentPosition(
      position => {
        setLocating(false)
        const { longitude: lon, latitude: lat } = position.coords
        if (bbox && !inBox(lon, lat, bbox)) {
          setHint('현재 위치가 광주광역시 밖입니다. 검색으로 출발지를 정하세요.')
          return
        }
        choose({ id: 'gps', name: '현재 위치', address: '', lon, lat, selectable: true, reason: null, source: 'gps' })
      },
      () => {
        setLocating(false)
        setHint('현재 위치를 가져오지 못했습니다. 검색이나 데모 지점으로 정하세요.')
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    )
  }

  const items = result?.items ?? []

  return (
    <div className="space-y-2">
      <Label htmlFor={`${id}-query`} className="route-label"><span className={`route-dot route-dot-${id}`} />{label}</Label>
      {value ? (
        <div className="flex items-start justify-between gap-2 pl-[18px]">
          <div className="min-w-0">
            <p className="truncate font-semibold">{value.name}</p>
            {value.address && <p className="truncate text-xs text-muted-foreground">{value.address}</p>}
          </div>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`${label} 지우기`}
            onClick={() => onChange(null)}>
            <X />
          </Button>
        </div>
      ) : (
        <>
          <form onSubmit={event => void search(event)} className="flex gap-2">
            <Input id={`${id}-query`} value={query} maxLength={50} placeholder="장소 이름이나 주소"
              onChange={event => setQuery(event.target.value)} autoComplete="off" />
            <Button type="submit" variant="outline" disabled={busy} aria-label={`${label} 검색`}>
              {busy ? <Loader2 className="animate-spin" /> : <Search />}
            </Button>
          </form>
          <div className="flex flex-wrap gap-2">
            {allowCurrentLocation && (
              <Button type="button" variant="outline" size="sm" onClick={currentLocation} disabled={locating}>
                {locating ? <Loader2 className="animate-spin" /> : <LocateFixed />}현재 위치
              </Button>
            )}
            <Button type="button" variant="ghost" size="sm" onClick={() => setShowDemo(v => !v)}
              aria-expanded={showDemo}>
              데모 지점에서 고르기
            </Button>
          </div>
        </>
      )}
      {hint && <p role="status" className="text-xs text-muted-foreground">{hint}</p>}
      {result?.notice && <p role="status" className="text-xs text-amber-200">{result.notice}</p>}
      {!value && items.length > 0 && (
        <ul className="max-h-56 space-y-1 overflow-y-auto rounded-lg border p-1" aria-label={`${label} 검색 결과`}>
          {items.map(item => (
            <li key={item.id}>
              <button type="button" disabled={!item.selectable} onClick={() => choose(item)}
                className="w-full rounded-md px-2 py-1.5 text-left hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60">
                <span className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{item.name}</span>
                  {!item.selectable && <Badge variant="outline">{item.reason ?? '선택 불가'}</Badge>}
                  {item.source === 'demo' && <Badge variant="secondary">데모</Badge>}
                </span>
                <span className="block truncate text-xs text-muted-foreground">{item.address}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!value && showDemo && (
        <ul className="space-y-1 rounded-lg border p-1" aria-label={`${label} 데모 지점`}>
          {demoPoints.map(point => (
            <li key={point.id}>
              <button type="button" onClick={() => choose(point)}
                className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted">
                {point.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
