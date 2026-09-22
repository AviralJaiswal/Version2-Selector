import React from 'react'
import { Mic, Square, Loader2 } from 'lucide-react'

export function MicButton({ isRecording, isTranscribing, onStart, onStop, disabled }) {
  if (isTranscribing) {
    return (
      <button type="button" className="mic-btn mic-btn-transcribing" disabled title="Transcribing...">
        <Loader2 size={18} className="spin" />
      </button>
    )
  }

  if (isRecording) {
    return (
      <button
        type="button"
        className="mic-btn mic-btn-recording"
        onClick={onStop}
        title="Stop recording"
        style={{ background: '#E31B23', color: 'white' }}
      >
        <Square size={16} />
      </button>
    )
  }

  return (
    <button
      type="button"
      className="mic-btn"
      onClick={onStart}
      disabled={disabled}
      title="Speak your message"
    >
      <Mic size={18} />
    </button>
  )
}
