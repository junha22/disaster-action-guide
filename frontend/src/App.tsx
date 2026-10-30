import { useEffect, useState, type FormEvent } from 'react'
import {
  Plus, RefreshCw, Save, Sparkles, Trash2,
  Database, Loader2, FileText
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card, CardContent, CardDescription,
  CardHeader, CardTitle
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription,
  DialogFooter, DialogHeader, DialogTitle
} from '@/components/ui/dialog'

import './App.css'

type RecordItem = {
  id: number
  title: string
  content: string
  ai_result: string | null
  created_at: string
  updated_at: string
}

type AIResponse = {
  record_id: number
  model_id: string
  mode: 'mock' | 'bedrock'
  ai_result: string
  usage?: {
    inputTokens?: number
    outputTokens?: number
  }
}

type GenerateResponse = {
  text: string
  model_id: string
  mode: 'mock' | 'bedrock'
}

const MODELS = [
  { id: 'global.anthropic.claude-haiku-4-5-20251001-v1:0', name: 'Claude Haiku 4.5 · 경제형' },
  { id: 'global.anthropic.claude-sonnet-5-5', name: 'Claude Sonnet 5.5 · 별도 호출 확인 필요' },
  { id: 'global.anthropic.claude-sonnet-5', name: 'Claude Sonnet 5' },
  { id: 'global.anthropic.claude-sonnet-4-6', name: 'Claude Sonnet 4.6' },
  { id: 'global.openai.gpt-6-sol', name: 'GPT-6 Sol' },
  { id: 'global.openai.gpt-5.6-sol', name: 'GPT-5.6 Sol' },
] as const

type ModelId = (typeof MODELS)[number]['id']

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body: unknown = response.status === 204
    ? null
    : await response.json().catch(() => null)

  if (!response.ok) {
    let message = `HTTP ${response.status}`
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = body.detail
      if (typeof detail === 'string') message = detail
    }
    throw new Error(message)
  }
  return body as T
}

function App() {
  const [records, setRecords] = useState<RecordItem[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [model, setModel] = useState<ModelId>(MODELS[0].id)
  const [instruction, setInstruction] = useState(
    '입력의 핵심 내용을 한국어로 간결하게 정리해줘.'
  )

  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'save' | 'ai' | 'delete' | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [aiMode, setAiMode] = useState<'mock' | 'bedrock' | null>(null)
  const [directText, setDirectText] = useState('')
  const [directResult, setDirectResult] = useState<GenerateResponse | null>(null)
  const [directBusy, setDirectBusy] = useState(false)
  const [directError, setDirectError] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [usage, setUsage] = useState<{
    id: number
    input: number
    output: number
  } | null>(null)

  const selected = records.find(r => r.id === selectedId)
  const processedCount = records.filter(r => r.ai_result).length

  async function loadRecords() {
    setLoading(true)
    try {
      const data = await api<RecordItem[]>('/api/records')
      setRecords(data)
      setError('')
    } catch {
      setError('API 서버 연결에 실패했습니다. 배포 설정을 확인하세요.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadRecords()
    void api<{ ai_mode: 'mock' | 'bedrock' }>('/api/health')
      .then(data => setAiMode(data.ai_mode))
      .catch(() => setAiMode(null))
  }, [])

  function newRecord() {
    setSelectedId(null)
    setTitle('')
    setContent('')
    setUsage(null)
    setError('')
    setMessage('')
  }

  function selectRecord(record: RecordItem) {
    setSelectedId(record.id)
    setTitle(record.title)
    setContent(record.content)
    setUsage(null)
    setError('')
    setMessage('')
  }

  async function saveRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return

    if (!title.trim()) {
      setError('제목을 입력하세요.')
      return
    }

    setBusy('save')
    setError('')
    setMessage('')

    try {
      const isEdit = selectedId !== null
      const saved = await api<RecordItem>(
        isEdit ? `/api/records/${selectedId}` : '/api/records',
        {
          method: isEdit ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title.trim(),
            content
          })
        }
      )

      setRecords(prev =>
        isEdit
          ? prev.map(r => r.id === saved.id ? saved : r)
          : [saved, ...prev]
      )
      setSelectedId(saved.id)
      setTitle(saved.title)
      setContent(saved.content)
      setMessage('기록이 저장되었습니다.')
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    } finally {
      setBusy(null)
    }
  }

  async function runAI() {
    if (selectedId === null || busy) return

    setBusy('ai')
    setError('')
    setMessage('')

    try {
      const result = await api<AIResponse>(
        `/api/records/${selectedId}/ai`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model_id: model,
            instruction
          })
        }
      )

      setRecords(prev => prev.map(r =>
        r.id === result.record_id
          ? { ...r, ai_result: result.ai_result }
          : r
      ))

      setUsage({
        id: result.record_id,
        input: result.usage?.inputTokens ?? 0,
        output: result.usage?.outputTokens ?? 0
      })
      setMessage(result.mode === 'mock'
        ? '로컬 모의 응답이 저장되었습니다. 실제 AI 결과가 아닙니다.'
        : 'AI 처리 결과가 저장되었습니다.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 처리 실패')
    } finally {
      setBusy(null)
    }
  }

  async function deleteRecord() {
    if (selectedId === null || busy) return

    setBusy('delete')
    setError('')

    try {
      await api<null>(`/api/records/${selectedId}`, {
        method: 'DELETE'
      })
      setRecords(prev => prev.filter(r => r.id !== selectedId))
      newRecord()
      setDeleteOpen(false)
      setMessage('기록이 삭제되었습니다.')
    } catch (e) {
      setError(e instanceof Error ? e.message : '삭제 실패')
    } finally {
      setBusy(null)
    }
  }

  async function runDirectAI(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (directBusy || !directText.trim() || !instruction.trim()) return
    setDirectBusy(true)
    setDirectError('')
    setDirectResult(null)
    try {
      setDirectResult(await api<GenerateResponse>('/api/ai/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: directText, model_id: model, instruction }),
      }))
    } catch (e) {
      setDirectError(e instanceof Error ? e.message : 'AI 호출 실패')
    } finally {
      setDirectBusy(false)
    }
  }

  return (
    <div className="kiro-app min-h-screen bg-background text-foreground">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-5">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <Badge variant="secondary">JNU AI HACKATHON</Badge>
            </div>
            <h1 className="text-2xl font-bold">Kirothon Starter</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              독립 AI 호출 · 선택형 기록 예제 · 팀별 기능 확장
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">FastAPI · React · SQLite</Badge>
            <Badge variant={aiMode === 'mock' ? 'secondary' : 'outline'}>
              {aiMode === 'mock' ? '로컬 모의 AI · AWS 미호출'
                : aiMode === 'bedrock' ? '서버 Bedrock AI' : 'AI 모드 확인 중'}
            </Badge>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 p-5">
        <Card>
          <CardHeader>
            <CardTitle>저장 없이 AI 호출</CardTitle>
            <CardDescription>
              기록 생성 없이 공통 AI API를 사용합니다. 입력과 응답은 기록 DB에 저장하지 않으며,
              호출 횟수만 공통 한도에 반영합니다. 모델·처리 지시는 기록 AI 예제와 공유합니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={event => void runDirectAI(event)} className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="direct-model">AI 모델</Label>
                  <select id="direct-model" value={model}
                    onChange={event => setModel(event.target.value as ModelId)}
                    disabled={directBusy || busy !== null}
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm">
                    {MODELS.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="direct-instruction">AI 처리 지시</Label>
                  <Input id="direct-instruction" value={instruction} maxLength={300}
                    onChange={event => setInstruction(event.target.value)} />
                </div>
              </div>
              <Label htmlFor="direct-text">AI에 전달할 입력</Label>
              <Textarea id="direct-text" value={directText}
                onChange={event => setDirectText(event.target.value)}
                maxLength={4000} rows={4} placeholder="팀 주제에 맞는 입력을 넣어 연동을 확인하세요" />
              <Button type="submit" disabled={directBusy || !directText.trim() || !instruction.trim()}>
                {directBusy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {aiMode === 'mock' ? '모의 응답 확인' : 'AI 호출'}
              </Button>
              {directError && <p role="alert" className="text-sm text-destructive">{directError}</p>}
              {directResult && (
                <div role="status" className="space-y-3 rounded-lg border bg-muted/30 p-4">
                  <Badge variant="outline">
                    {directResult.mode === 'mock' ? '모의 응답 · 실제 AI 결과 아님' : 'Bedrock 응답'}
                  </Badge>
                  <p className="whitespace-pre-wrap break-words text-sm leading-7">{directResult.text}</p>
                </div>
              )}
            </form>
          </CardContent>
        </Card>
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <CardContent className="flex items-center gap-3 py-5">
              <Database className="h-7 w-7 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">조회된 기록</p>
                <p className="text-2xl font-bold">{records.length}</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3 py-5">
              <Sparkles className="h-7 w-7 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">AI 처리 완료</p>
                <p className="text-2xl font-bold">{processedCount}</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {error && (
          <div role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm">
            {error}
          </div>
        )}
        {message && (
          <div role="status" className="rounded-lg border bg-muted p-4 text-sm">
            {message}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5" />
                {selectedId === null ? '새 기록 작성' : '기록 수정'}
              </CardTitle>
              <CardDescription>
                제목과 내용을 입력하고 SQLite에 저장합니다.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={saveRecord} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="record-title">제목</Label>
                  <Input
                    id="record-title"
                    value={title}
                    onChange={e => setTitle(e.target.value)}
                    maxLength={180}
                    placeholder="제목을 입력하세요"
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="record-content">내용</Label>
                  <Textarea
                    id="record-content"
                    value={content}
                    onChange={e => setContent(e.target.value)}
                    maxLength={3600}
                    rows={7}
                    placeholder="자유롭게 내용을 입력하세요"
                  />
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={busy !== null}>
                    {busy === 'save'
                      ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      : <Save className="mr-2 h-4 w-4" />}
                    {selectedId === null ? '기록 저장' : '수정 저장'}
                  </Button>

                  <Button type="button" variant="outline"
                    onClick={newRecord} disabled={busy !== null}>
                    <Plus className="mr-2 h-4 w-4" />
                    새 기록
                  </Button>

                  {selectedId !== null && (
                    <Button type="button" variant="destructive"
                      onClick={() => setDeleteOpen(true)}
                      disabled={busy !== null}>
                      <Trash2 className="mr-2 h-4 w-4" />
                      삭제
                    </Button>
                  )}
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle>기록 목록</CardTitle>
                <Button variant="outline" size="sm"
                  onClick={() => void loadRecords()}
                  disabled={loading || busy !== null}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  새로고침
                </Button>
              </div>
              <CardDescription>
                최근 기록 최대 100개를 표시합니다.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <p className="text-sm text-muted-foreground">불러오는 중...</p>
              ) : records.length === 0 ? (
                <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                  저장된 기록이 없습니다.
                </div>
              ) : (
                <div className="max-h-[420px] space-y-2 overflow-y-auto">
                  {records.map(record => (
                    <Button key={record.id}
                      type="button"
                      variant="outline"
                      disabled={busy !== null}
                      onClick={() => selectRecord(record)}
                      className={
                        'h-auto w-full justify-start whitespace-normal p-4 text-left ' +
                        (selectedId === record.id ? 'border-primary bg-primary/5' : '')
                      }>
                      <span className="block w-full min-w-0">
                        <span className="block truncate font-semibold">
                          {record.title}
                        </span>
                        <span className="mt-1 block truncate text-xs text-muted-foreground">
                          {record.content || '내용 없음'}
                        </span>
                        <span className="mt-2 block">
                          <Badge variant={record.ai_result ? 'secondary' : 'outline'}>
                            {record.ai_result ? 'AI 처리 완료' : '미처리'}
                          </Badge>
                        </span>
                      </span>
                    </Button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              Bedrock AI 처리
            </CardTitle>
            <CardDescription>
              저장된 기록을 선택하고 허용된 모델로 AI 처리를 실행합니다.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="ai-model">AI 모델</Label>
                <select id="ai-model"
                  value={model}
                  onChange={e => setModel(e.target.value as ModelId)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  disabled={busy !== null}>
                  {MODELS.map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="ai-instruction">AI 처리 지시</Label>
                <Input id="ai-instruction"
                  value={instruction}
                  onChange={e => setInstruction(e.target.value)}
                  maxLength={300}
                />
              </div>
            </div>

            <Button type="button" onClick={() => void runAI()}
              disabled={!selected || busy !== null || !instruction.trim()}>
              {busy === 'ai'
                ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                : <Sparkles className="mr-2 h-4 w-4" />}
              AI 처리 및 결과 저장
            </Button>

            <div className="rounded-lg border bg-muted/30 p-5">
              <h2 className="mb-3 text-sm font-semibold">AI 처리 결과</h2>
              {selected?.ai_result ? (
                <>
                  <div className="whitespace-pre-wrap break-words text-sm leading-7">
                    {selected.ai_result}
                  </div>
                  {usage?.id === selected.id && (
                    <p className="mt-4 text-xs text-muted-foreground">
                      입력 {usage.input} / 출력 {usage.output} 토큰
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  처리된 결과가 없습니다. 기록을 저장하고 AI를 실행하세요.
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        <p className="pb-6 text-center text-xs text-muted-foreground">
          Kirothon Starter · 주제별 기능은 각 팀이 자유롭게 확장
        </p>
      </main>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>기록 삭제</DialogTitle>
            <DialogDescription>
              선택한 기록과 AI 결과를 삭제할까요?
              이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" disabled={busy !== null}
              onClick={() => setDeleteOpen(false)}>취소</Button>
            <Button variant="destructive" disabled={busy !== null}
              onClick={() => void deleteRecord()}>삭제</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default App
