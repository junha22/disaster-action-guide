// Spoken alerts through the browser's own speech engine. Silent where it is missing.
const COUNTERS = ['', '한', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉']

export function speechSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

// Written forms a speech engine tends to read oddly: "75mm", "1곳".
export function spokenText(text: string): string {
  return text
    .replace(/(\d)mm/g, '$1밀리미터')
    .replace(/(?<!\d)([1-9])곳/g, (_, digit: string) => `${COUNTERS[Number(digit)]} 곳`)
}

function koreanVoice(): SpeechSynthesisVoice | undefined {
  return window.speechSynthesis.getVoices().find(voice => voice.lang.toLowerCase().startsWith('ko'))
}

// One utterance per sentence: some engines stop in the middle of a long one.
export function speak(text: string, { interrupt = false } = {}) {
  if (!speechSupported()) return
  const synth = window.speechSynthesis
  if (interrupt) synth.cancel()
  for (const sentence of spokenText(text).split(/(?<=[.!?])\s+/)) {
    if (!sentence.trim()) continue
    const utterance = new SpeechSynthesisUtterance(sentence)
    utterance.lang = 'ko-KR'
    const voice = koreanVoice()
    if (voice) utterance.voice = voice
    synth.speak(utterance)
  }
}

export function stopSpeaking() {
  if (speechSupported()) window.speechSynthesis.cancel()
}
