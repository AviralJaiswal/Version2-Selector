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
 * Supports single compact audio button with pause & resume at paused position.
 */
export function useVoiceMode() {
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [activeMessageId, setActiveMessageId] = useState(null)
  const [voiceError, setVoiceError] = useState('')

  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const audioElRef = useRef(null)
  const recognitionRef = useRef(null)
  const speechResultRef = useRef('')
  const playbackModeRef = useRef(null) // 'audio' | 'speechSynthesis' | null
  const currentTextRef = useRef('')

  const startRecording = useCallback(async () => {
    // Automatically stop any ongoing playback when recording starts
    if (audioElRef.current) {
      audioElRef.current.pause()
      audioElRef.current.currentTime = 0
      audioElRef.current = null
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    playbackModeRef.current = null
    setIsSpeaking(false)
    setIsPaused(false)
    setActiveMessageId(null)

    setVoiceError('')
    speechResultRef.current = ''

    // 1. Start Web Speech API SpeechRecognition if supported (instantaneous client-side recognition)
    const SpeechRecognition = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null
    if (SpeechRecognition) {
      try {
        const recognition = new SpeechRecognition()
        recognition.continuous = true
        recognition.interimResults = true
        recognition.lang = '' // browser auto-detection
        recognition.onresult = (event) => {
          let fullTranscript = ''
          for (let i = 0; i < event.results.length; i++) {
            fullTranscript += event.results[i][0].transcript + ' '
          }
          speechResultRef.current = fullTranscript.trim()
        }
        recognition.onerror = (e) => {
          console.warn('SpeechRecognition info:', e.error)
        }
        recognition.start()
        recognitionRef.current = recognition
      } catch (err) {
        console.warn('Native speech recognition init note:', err)
      }
    }

    // 2. Also start MediaRecorder for audio capture / server fallback
    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        const recorder = new MediaRecorder(stream)
        chunksRef.current = []
        recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
        recorder.start()
        mediaRecorderRef.current = recorder
      }
      setIsRecording(true)
    } catch (err) {
      if (!recognitionRef.current) {
        setVoiceError('Microphone access denied or unavailable.')
      } else {
        setIsRecording(true)
      }
    }
  }, [])

  // Stops recording and returns the transcribed text
  const stopRecordingAndTranscribe = useCallback(() => {
    return new Promise((resolve) => {
      // Stop native recognition if active
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop()
        } catch (e) {}
        recognitionRef.current = null
      }

      const recorder = mediaRecorderRef.current
      if (!recorder) {
        setIsRecording(false)
        const text = speechResultRef.current.trim()
        if (text) {
          resolve(text)
        } else {
          setVoiceError('No speech detected. Please try speaking again.')
          resolve('')
        }
        return
      }

      recorder.onstop = async () => {
        setIsRecording(false)

        // 1. If native speech recognition captured speech, resolve immediately!
        if (speechResultRef.current && speechResultRef.current.trim()) {
          resolve(speechResultRef.current.trim())
          return
        }

        // 2. Otherwise send audio bytes to backend Whisper
        setIsTranscribing(true)
        try {
          const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
          if (blob.size < 100) {
            resolve('')
            return
          }
          const audioBase64 = await blobToBase64(blob)
          const res = await fetch(`${API}/api/v1/voice/transcribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ audio_base64: audioBase64, language: null }),
          })
          if (res.ok) {
            const body = await res.json()
            const text = body.data?.text || body.text || ''
            if (text) {
              resolve(text)
              return
            }
          }
          if (speechResultRef.current && speechResultRef.current.trim()) {
            resolve(speechResultRef.current.trim())
          } else {
            setVoiceError('Could not transcribe audio. Please try typing or speak again.')
            resolve('')
          }
        } catch (err) {
          if (speechResultRef.current && speechResultRef.current.trim()) {
            resolve(speechResultRef.current.trim())
          } else {
            setVoiceError('Transcription failed. Please try typing instead.')
            resolve('')
          }
        } finally {
          setIsTranscribing(false)
        }
      }

      recorder.stop()
      recorder.stream.getTracks().forEach((t) => t.stop())
    })
  }, [])

  const cancelRecording = useCallback(() => {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop() } catch (e) {}
      recognitionRef.current = null
    }
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      recorder.stop()
      recorder.stream.getTracks().forEach((t) => t.stop())
    }
    setIsRecording(false)
  }, [])

  // Completely stops and cleans up audio playback
  const stopSpeaking = useCallback(() => {
    if (audioElRef.current) {
      audioElRef.current.pause()
      audioElRef.current.currentTime = 0
      audioElRef.current = null
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    playbackModeRef.current = null
    currentTextRef.current = ''
    setIsSpeaking(false)
    setIsPaused(false)
    setActiveMessageId(null)
  }, [])

  // Pauses speaking at current position
  const pauseSpeaking = useCallback(() => {
    if (playbackModeRef.current === 'audio' && audioElRef.current) {
      audioElRef.current.pause()
      setIsSpeaking(false)
      setIsPaused(true)
    } else if (playbackModeRef.current === 'speechSynthesis' && typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.pause()
      setIsSpeaking(false)
      setIsPaused(true)
    }
  }, [])

  // Resumes speaking from paused position
  const resumeSpeaking = useCallback(() => {
    if (playbackModeRef.current === 'audio' && audioElRef.current) {
      audioElRef.current.play().then(() => {
        setIsSpeaking(true)
        setIsPaused(false)
      }).catch(() => {
        stopSpeaking()
      })
    } else if (playbackModeRef.current === 'speechSynthesis' && typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.resume()
      setIsSpeaking(true)
      setIsPaused(false)
    }
  }, [stopSpeaking])

  // Speaks text aloud from the beginning with single playback guarantee
  const speak = useCallback(async (text, messageId = 'latest') => {
    if (!text || !text.trim()) return

    // Guarantee never multiple audio playing simultaneously
    if (audioElRef.current) {
      audioElRef.current.pause()
      audioElRef.current = null
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }

    currentTextRef.current = text
    setActiveMessageId(messageId)
    setIsSpeaking(true)
    setIsPaused(false)

    try {
      const res = await fetch(`${API}/api/v1/voice/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language: null }),
      })
      const body = await res.json()
      const data = body.data || body

      if (data.used_fallback || !data.audio_base64) {
        playbackModeRef.current = 'speechSynthesis'
        speakWithBrowserTts(text, () => {
          setIsSpeaking(false)
          setIsPaused(false)
          setActiveMessageId(null)
          playbackModeRef.current = null
        })
        return
      }

      playbackModeRef.current = 'audio'
      const audio = new Audio(`data:audio/wav;base64,${data.audio_base64}`)
      audioElRef.current = audio

      audio.onended = () => {
        setIsSpeaking(false)
        setIsPaused(false)
        setActiveMessageId(null)
        playbackModeRef.current = null
        audioElRef.current = null
      }

      audio.onerror = () => {
        playbackModeRef.current = 'speechSynthesis'
        speakWithBrowserTts(text, () => {
          setIsSpeaking(false)
          setIsPaused(false)
          setActiveMessageId(null)
          playbackModeRef.current = null
        })
      }

      await audio.play()
    } catch (err) {
      playbackModeRef.current = 'speechSynthesis'
      speakWithBrowserTts(text, () => {
        setIsSpeaking(false)
        setIsPaused(false)
        setActiveMessageId(null)
        playbackModeRef.current = null
      })
    }
  }, [])

  // One compact toggle action: plays, pauses, or resumes from paused position
  const togglePlayPause = useCallback((text, messageId = 'latest') => {
    if (activeMessageId === messageId) {
      if (isSpeaking) {
        pauseSpeaking()
      } else if (isPaused) {
        resumeSpeaking()
      } else {
        speak(text, messageId)
      }
    } else {
      speak(text, messageId)
    }
  }, [activeMessageId, isSpeaking, isPaused, pauseSpeaking, resumeSpeaking, speak])

  return {
    isRecording,
    isTranscribing,
    isSpeaking,
    isPaused,
    activeMessageId,
    voiceError,
    startRecording,
    stopRecordingAndTranscribe,
    cancelRecording,
    speak,
    pauseSpeaking,
    resumeSpeaking,
    stopSpeaking,
    togglePlayPause,
    micSupported: typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
  }
}

function detectScriptLocale(text) {
  if (!text) return 'en-IN'
  if (/[\u0900-\u097F]/.test(text)) return 'hi-IN'  // Hindi / Devanagari
  if (/[\u0C00-\u0C7F]/.test(text)) return 'te-IN'  // Telugu
  if (/[\u0B80-\u0BFF]/.test(text)) return 'ta-IN'  // Tamil
  if (/[\u0C80-\u0CFF]/.test(text)) return 'kn-IN'  // Kannada
  if (/[\u0D00-\u0D7F]/.test(text)) return 'ml-IN'  // Malayalam
  if (/[\u0980-\u09FF]/.test(text)) return 'bn-IN'  // Bengali
  if (/[\u0A80-\u0AFF]/.test(text)) return 'gu-IN'  // Gujarati
  return 'en-IN'
}

function speakWithBrowserTts(text, onDone) {
  if (typeof window === 'undefined' || !window.speechSynthesis) { onDone(); return }
  const cleanText = text.replace(/[*#_`]/g, '').trim()
  const utterance = new SpeechSynthesisUtterance(cleanText)
  const locale = detectScriptLocale(cleanText)
  utterance.lang = locale

  const voices = window.speechSynthesis.getVoices()
  const matchedVoice = voices.find((v) => v.lang === locale || v.lang.startsWith(locale.split('-')[0]))
  if (matchedVoice) {
    utterance.voice = matchedVoice
  }

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
