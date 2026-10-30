// Spoken guidance. First choice: the server's Supertonic 3 voice (F1, "Sarah") via POST /api/tts.
// When that fails (no service, timeout, autoplay blocked) the browser's own Korean voice reads it.
// Sentences play in order; a new interrupting message stops whatever is playing.
const COUNTERS = ['', '한', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉']
const TTS_TIMEOUT_MS = 8000
const AUDIO_CACHE_SIZE = 40

export function speechSupported(): boolean {
  return typeof window !== 'undefined' && (typeof Audio !== 'undefined' || 'speechSynthesis' in window)
}

// Written forms a speech engine tends to read oddly: "75mm", "1곳".
export function spokenText(text: string): string {
  return text
    .replace(/(\d)mm/g, '$1밀리미터')
    .replace(/(?<!\d)([1-9])곳/g, (_, digit: string) => `${COUNTERS[Number(digit)]} 곳`)
}

// ---- server voice -------------------------------------------------------------------------------

const audioCache = new Map<string, Promise<string | null>>()

function serverAudio(text: string): Promise<string | null> {
  const cached = audioCache.get(text)
  if (cached) return cached
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), TTS_TIMEOUT_MS)
  const pending = fetch('/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal: controller.signal,
  })
    .then(response => (response.ok ? response.blob() : null))
    .then(blob => (blob && blob.size > 0 ? URL.createObjectURL(blob) : null))
    .catch(() => null)
    .finally(() => window.clearTimeout(timer))
  // Failures are not kept, so the next message tries the server again.
  pending.then(url => {
    if (!url) audioCache.delete(text)
  })
  audioCache.set(text, pending)
  while (audioCache.size > AUDIO_CACHE_SIZE) {
    const oldest = audioCache.keys().next().value as string
    audioCache.get(oldest)?.then(url => url && URL.revokeObjectURL(url))
    audioCache.delete(oldest)
  }
  return pending
}

let generation = 0
let queue: Promise<void> = Promise.resolve()
let player: HTMLAudioElement | null = null
let playing = false

// One shared player. Mobile browsers (iOS Safari) only let an audio element play after a user
// gesture, so the first tap or key press anywhere plays a tiny silent clip on it to unlock it.
function sharedPlayer(): HTMLAudioElement {
  if (!player) player = new Audio()
  return player
}

function silentClip(): string {
  const bytes = new Uint8Array(45)
  const view = new DataView(bytes.buffer)
  const ascii = (offset: number, text: string) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)))
  ascii(0, 'RIFF'); view.setUint32(4, 37, true); ascii(8, 'WAVE'); ascii(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, 8000, true); view.setUint32(28, 8000, true); view.setUint16(32, 1, true)
  view.setUint16(34, 8, true); ascii(36, 'data'); view.setUint32(40, 1, true); view.setUint8(44, 128)
  return URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
}

function unlockOnFirstGesture() {
  if (typeof window === 'undefined' || typeof Audio === 'undefined') return
  const unlock = () => {
    window.removeEventListener('pointerdown', unlock, true)
    window.removeEventListener('keydown', unlock, true)
    const audio = sharedPlayer()
    if (playing) return
    audio.src = silentClip()
    audio.play().catch(() => undefined)
  }
  window.addEventListener('pointerdown', unlock, true)
  window.addEventListener('keydown', unlock, true)
}
unlockOnFirstGesture()

function playUrl(url: string, gen: number): Promise<boolean> {
  return new Promise(resolve => {
    if (gen !== generation) return resolve(true)
    const audio = sharedPlayer()
    let settled = false
    const done = (ok: boolean) => {
      if (settled) return
      settled = true
      playing = false
      audio.onended = audio.onerror = audio.onpause = null
      resolve(ok)
    }
    audio.onended = () => done(true)
    audio.onerror = () => done(false)
    audio.onpause = () => done(true) // stopSpeaking() pauses it
    playing = true
    audio.src = url
    audio.play().catch(() => done(false)) // e.g. autoplay blocked: fall back to the browser voice
  })
}

// ---- browser voice --------------------------------------------------------------------------------

function koreanVoice(): SpeechSynthesisVoice | undefined {
  return window.speechSynthesis.getVoices().find(voice => voice.lang.toLowerCase().startsWith('ko'))
}

// One utterance per sentence: some engines stop in the middle of a long one.
function browserSpeak(text: string, gen: number): Promise<void> {
  if (!('speechSynthesis' in window) || gen !== generation) return Promise.resolve()
  const sentences = text.split(/(?<=[.!?])\s+/).filter(s => s.trim())
  return new Promise(resolve => {
    if (!sentences.length) return resolve()
    const synth = window.speechSynthesis
    const voice = koreanVoice()
    sentences.forEach((sentence, i) => {
      const utterance = new SpeechSynthesisUtterance(sentence)
      utterance.lang = 'ko-KR'
      if (voice) utterance.voice = voice
      if (i === sentences.length - 1) {
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
      }
      synth.speak(utterance)
    })
  })
}

// ---- public ---------------------------------------------------------------------------------------

export function speak(text: string, { interrupt = false } = {}) {
  if (!speechSupported()) return
  const spoken = spokenText(text).trim()
  if (!spoken) return
  if (interrupt) stopSpeaking()
  const gen = generation
  const audio = serverAudio(spoken) // synthesis starts now, playback waits for its turn
  queue = queue.then(async () => {
    if (gen !== generation) return
    const url = await audio
    if (gen !== generation) return
    if (url && await playUrl(url, gen)) return
    await browserSpeak(spoken, gen)
  })
}

export function stopSpeaking() {
  generation += 1
  queue = Promise.resolve()
  if (playing) player?.pause()
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
}
