import { useState, useRef, useCallback } from 'react'
import { API } from '../utils/api'

// Maps our 4 supported language codes to BCP-47 tags the browser's
// SpeechSynthesis API expects for voice selection.
const SPEECH_SYNTH_LOCALE = {
  en: 'en-IN',
  hi: 'hi-IN',
  te: 'te-IN',
  ta: 'ta-IN',
}

/**
 * Voice mode: mic recording -> STT (self-hosted Whisper), and
 * text -> TTS (self-hosted Indic Parler, falling back to the browser's
 * own SpeechSynthesis API if the model is slow/unavailable).
 *
 * Both the STT and TTS backends are genuinely free (no API key, no
 * per-request cost) - see app/services/voice_service.py.
 */
export function useVoiceMode(language) {
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const audioElRef = useRef(null)

  const startRecording = useCallback(async () => {
    setVoiceError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      recorder.start()
      mediaRecorderRef.current = recorder
      setIsRecording(true)
    } catch (err) {
      setVoiceError('Microphone access denied or unavailable.')
    }
  }, [])

  // Stops recording and returns the transcribed text (or '' on failure).
  const stopRecordingAndTranscribe = useCallback(() => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current
      if (!recorder) { resolve(''); return }

      recorder.onstop = async () => {
        setIsRecording(false)
        setIsTranscribing(true)
        try {
          const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
          const audioBase64 = await blobToBase64(blob)
          const res = await fetch(`${API}/api/v1/voice/transcribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ audio_base64: audioBase64, language }),
          })
          if (!res.ok) {
            setVoiceError('Could not transcribe audio. Please try typing instead.')
            resolve('')
            return
          }
          const body = await res.json()
          resolve(body.data?.text || body.text || '')
        } catch (err) {
          setVoiceError('Transcription failed. Please try typing instead.')
          resolve('')
        } finally {
          setIsTranscribing(false)
        }
      }
      recorder.stop()
      recorder.stream.getTracks().forEach((t) => t.stop())
    })
  }, [language])

  const cancelRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      recorder.stop()
      recorder.stream.getTracks().forEach((t) => t.stop())
    }
    setIsRecording(false)
  }, [])

  // Speaks `text` aloud: tries the self-hosted Indic Parler TTS first,
  // falls back to the browser's built-in SpeechSynthesis if that model
  // is unavailable or too slow (server signals this via used_fallback).
  const speak = useCallback(async (text) => {
    if (!text || !text.trim()) return
    setIsSpeaking(true)
    try {
      const res = await fetch(`${API}/api/v1/voice/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language }),
      })
      const body = await res.json()
      const data = body.data || body

      if (data.used_fallback || !data.audio_base64) {
        speakWithBrowserTts(text, language, () => setIsSpeaking(false))
        return
      }

      const audio = new Audio(`data:audio/wav;base64,${data.audio_base64}`)
      audioElRef.current = audio
      audio.onended = () => setIsSpeaking(false)
      audio.onerror = () => {
        // Even a playback failure falls back to browser TTS rather than
        // going silent.
        speakWithBrowserTts(text, language, () => setIsSpeaking(false))
      }
      await audio.play()
    } catch (err) {
      speakWithBrowserTts(text, language, () => setIsSpeaking(false))
    }
  }, [language])

  const stopSpeaking = useCallback(() => {
    if (audioElRef.current) {
      audioElRef.current.pause()
      audioElRef.current = null
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    setIsSpeaking(false)
  }, [])

  return {
    isRecording,
    isTranscribing,
    isSpeaking,
    voiceError,
    startRecording,
    stopRecordingAndTranscribe,
    cancelRecording,
    speak,
    stopSpeaking,
    micSupported: typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
  }
}

function speakWithBrowserTts(text, language, onDone) {
  if (typeof window === 'undefined' || !window.speechSynthesis) { onDone(); return }
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = SPEECH_SYNTH_LOCALE[language] || 'en-IN'
  utterance.onend = onDone
  utterance.onerror = onDone
  window.speechSynthesis.speak(utterance)
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve(reader.result.split(',')[1])
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}
