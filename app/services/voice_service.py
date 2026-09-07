"""Voice mode: speech-to-text (Whisper) and text-to-speech (Indic Parler TTS).

Both models are self-hosted and genuinely free (no per-request cost, no API
key needed) - faster-whisper (medium) for STT across en/hi/te/ta, and
AI4Bharat's Indic Parler TTS for natural Hindi/Tamil/Telugu voice output,
with English handled by the same model.

Models are lazy-loaded on first use, not at import time, so starting the
server doesn't pay the (multi-GB, tens-of-seconds) model load cost unless
voice mode is actually used. Both are wrapped so a failure here degrades
the response gracefully (falls back to browser-side TTS, or returns a clear
error for STT) rather than crashing the request.
"""
from __future__ import annotations

import io
import logging
import time

from app.config import get_settings
from app.utils.trace import trace

logger = logging.getLogger(__name__)

# Whisper language codes for our four supported languages.
WHISPER_LANGUAGE_MAP = {
    "en": "en",
    "hi": "hi",
    "te": "te",
    "ta": "ta",
}

# Indic Parler TTS speaker descriptions per language - chosen for clarity
# and a neutral, professional tone suited to a customer-support assistant.
# See https://huggingface.co/ai4bharat/indic-parler-tts for the description
# vocabulary this model was trained to follow.
TTS_VOICE_DESCRIPTIONS = {
    "en": "A clear, professional female voice speaks at a moderate pace with minimal background noise, in a friendly customer support tone.",
    "hi": "Divya speaks in a clear, warm voice at a moderate pace with minimal background noise, in a friendly customer support tone.",
    "te": "Lalitha speaks in a clear, warm voice at a moderate pace with minimal background noise, in a friendly customer support tone.",
    "ta": "Jaya speaks in a clear, warm voice at a moderate pace with minimal background noise, in a friendly customer support tone.",
}

_whisper_model = None
_tts_model = None
_tts_tokenizer = None
_tts_description_tokenizer = None


class VoiceServiceError(Exception):
    """Raised when STT or TTS genuinely fails (not a fallback-eligible slowness)."""


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        settings = get_settings()
        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s (first use, may take a while)",
            settings.whisper_model_size, settings.whisper_device, settings.whisper_compute_type,
        )
        _whisper_model = WhisperModel(
            settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    return _whisper_model


@trace
def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """Transcribe audio to text using Whisper.

    Returns {"text": str, "language": str, "duration_seconds": float}.
    Raises VoiceServiceError on genuine failure (corrupt audio, model load
    failure) - the caller should return a clear error to the user, since
    there's no good silent fallback for STT the way there is for TTS.
    """
    settings = get_settings()
    if not settings.voice_enabled:
        raise VoiceServiceError("Voice mode is disabled on this server.")

    whisper_lang = WHISPER_LANGUAGE_MAP.get(language)
    if whisper_lang is None:
        raise VoiceServiceError(f"Unsupported voice language: {language!r}")

    try:
        model = _get_whisper_model()
        start = time.monotonic()
        segments, info = model.transcribe(
            io.BytesIO(audio_bytes),
            language=whisper_lang,
            vad_filter=True,  # skip silence, improves accuracy on real mic audio
            beam_size=5,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.monotonic() - start
        return {"text": text, "language": whisper_lang, "duration_seconds": round(elapsed, 2)}
    except VoiceServiceError:
        raise
    except Exception as exc:
        logger.exception("Whisper transcription failed: %s", exc)
        raise VoiceServiceError(f"Transcription failed: {exc}") from exc


def _get_tts_model():
    global _tts_model, _tts_tokenizer, _tts_description_tokenizer
    if _tts_model is None:
        import torch
        from transformers import AutoTokenizer
        from parler_tts import ParlerTTSForConditionalGeneration

        device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.bfloat16 if device != "cpu" else torch.float32
        repo_id = "ai4bharat/indic-parler-tts"

        logger.info("Loading Indic Parler TTS on device=%s (first use, may take a while)", device)
        _tts_model = ParlerTTSForConditionalGeneration.from_pretrained(
            repo_id, torch_dtype=torch_dtype
        ).to(device)
        _tts_tokenizer = AutoTokenizer.from_pretrained(repo_id)
        _tts_description_tokenizer = AutoTokenizer.from_pretrained(_tts_model.config.text_encoder._name_or_path)
    return _tts_model, _tts_tokenizer, _tts_description_tokenizer


@trace
def synthesize_speech(text: str, language: str = "en") -> dict:
    """Generate speech audio for `text` using Indic Parler TTS.

    Returns {"audio_bytes": bytes, "sample_rate": int, "used_fallback": False}
    on success. If generation exceeds indic_tts_timeout_seconds or the model
    fails to load/run, returns {"audio_bytes": None, "used_fallback": True,
    "text": text} instead of raising - the caller (frontend) is expected to
    speak `text` via the browser's own SpeechSynthesis API in that case, so
    voice output degrades gracefully rather than going silent.
    """
    settings = get_settings()
    if not settings.indic_tts_enabled or not text.strip():
        return {"audio_bytes": None, "used_fallback": True, "text": text}

    description = TTS_VOICE_DESCRIPTIONS.get(language, TTS_VOICE_DESCRIPTIONS["en"])

    try:
        import torch
        import soundfile as sf

        start = time.monotonic()
        model, tokenizer, description_tokenizer = _get_tts_model()

        device = next(model.parameters()).device
        input_ids = description_tokenizer(description, return_tensors="pt").input_ids.to(device)
        prompt_input_ids = tokenizer(text, return_tensors="pt").input_ids.to(device)

        with torch.no_grad():
            generation = model.generate(input_ids=input_ids, prompt_input_ids=prompt_input_ids)

        elapsed = time.monotonic() - start
        if elapsed > settings.indic_tts_timeout_seconds:
            logger.warning(
                "Indic Parler TTS took %.1fs (over %.1fs budget) - signaling fallback for this response",
                elapsed, settings.indic_tts_timeout_seconds,
            )
            return {"audio_bytes": None, "used_fallback": True, "text": text}

        audio_arr = generation.cpu().numpy().squeeze()
        buf = io.BytesIO()
        sf.write(buf, audio_arr, model.config.sampling_rate, format="WAV")
        return {
            "audio_bytes": buf.getvalue(),
            "sample_rate": model.config.sampling_rate,
            "used_fallback": False,
            "duration_seconds": round(elapsed, 2),
        }
    except Exception as exc:
        logger.warning("Indic Parler TTS failed, falling back to browser TTS: %s", exc)
        return {"audio_bytes": None, "used_fallback": True, "text": text}
