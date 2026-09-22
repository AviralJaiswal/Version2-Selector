"""Voice mode: speech-to-text (AI4Bharat Indic Conformer) and text-to-speech (Indic Parler TTS).

STT: AI4Bharat's Indic Conformer 600M multilingual ASR model provides
high-accuracy speech recognition for 22 Indian languages. The model runs
locally via ONNX Runtime — no API key or per-request cost. For English,
the frontend's browser Web Speech API is used instead (the Indic Conformer
does not cover English).

TTS: AI4Bharat's Indic Parler TTS for natural Hindi/Tamil/Telugu voice
output, with English handled by the same model.

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

# Indic Conformer supported language codes (22 scheduled Indian languages).
# English is NOT supported — the frontend's Web Speech API handles English.
INDIC_CONFORMER_LANGUAGE_MAP = {
    "hi": "hi",   # Hindi
    "te": "te",   # Telugu
    "ta": "ta",   # Tamil
    "bn": "bn",   # Bengali
    "mr": "mr",   # Marathi
    "gu": "gu",   # Gujarati
    "kn": "kn",   # Kannada
    "ml": "ml",   # Malayalam
    "pa": "pa",   # Punjabi
    "or": "or",   # Odia
    "as": "as",   # Assamese
    "ur": "ur",   # Urdu
    "ne": "ne",   # Nepali
    "sa": "sa",   # Sanskrit
    "sd": "sd",   # Sindhi
    "ks": "ks",   # Kashmiri
    "doi": "doi", # Dogri
    "kok": "kok", # Konkani
    "mai": "mai", # Maithili
    "sat": "sat", # Santali
    "mni": "mni", # Manipuri
    "brx": "brx", # Bodo
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

_conformer_model = None
_tts_model = None
_tts_tokenizer = None
_tts_description_tokenizer = None


class VoiceServiceError(Exception):
    """Raised when STT or TTS genuinely fails (not a fallback-eligible slowness)."""


def _get_indic_conformer_model():
    """Lazy-load the AI4Bharat Indic Conformer 600M ASR model.

    The model is loaded via HuggingFace transformers with trust_remote_code=True
    (required for the custom Conformer architecture). Uses ONNX Runtime
    internally for inference. The HF token is needed because the repo is gated.
    """
    global _conformer_model
    if _conformer_model is None:
        from transformers import AutoModel

        settings = get_settings()
        hf_token = settings.hf_token
        model_id = settings.indic_conformer_model

        logger.info(
            "Loading Indic Conformer ASR model=%s (first use, may take a while — ~2.4 GB download)",
            model_id,
        )
        _conformer_model = AutoModel.from_pretrained(
            model_id,
            trust_remote_code=True,
            token=hf_token,
        )
        logger.info("Indic Conformer ASR model loaded successfully.")
    return _conformer_model


def _audio_bytes_to_tensor(audio_bytes: bytes):
    """Convert raw audio bytes (webm/wav/ogg from the browser) to a 16kHz mono tensor.

    The Indic Conformer model strictly requires 16kHz mono audio input.
    Returns a torch tensor of shape (1, num_samples).
    """
    import torch
    import torchaudio

    # Load audio from bytes buffer
    buf = io.BytesIO(audio_bytes)
    try:
        wav, sr = torchaudio.load(buf)
    except Exception:
        # torchaudio might fail on some formats (e.g. webm); try soundfile as fallback
        import soundfile as sf
        buf.seek(0)
        data, sr = sf.read(buf)
        wav = torch.tensor(data, dtype=torch.float32)
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)
        elif wav.ndim == 2 and wav.shape[1] <= 8:
            # soundfile returns (samples, channels) — transpose to (channels, samples)
            wav = wav.T

    # Convert stereo/multi-channel to mono
    if wav.shape[0] > 1:
        wav = torch.mean(wav, dim=0, keepdim=True)

    # Resample to 16kHz if necessary
    target_sr = 16000
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)
        wav = resampler(wav)

    return wav


@trace
def transcribe_audio(audio_bytes: bytes, language: str | None = None) -> dict:
    """Transcribe audio to text using AI4Bharat Indic Conformer 600M.

    For Indic languages (hi, te, ta, etc.), uses the server-side Conformer model
    for high-accuracy transcription. For English or unsupported languages, returns
    a signal for the frontend to use the browser's Web Speech API instead.

    Returns {"text": str, "language": str, "duration_seconds": float} on success,
    or {"text": "", "language": "en", "use_browser_stt": True} for English/unsupported.
    """
    settings = get_settings()
    if not settings.voice_enabled:
        raise VoiceServiceError("Voice mode is disabled on this server.")

    # Determine the target language for the Conformer model
    effective_lang = language if (language and language != "auto") else None

    # If language is English or not specified, signal the frontend to use browser STT
    # The Indic Conformer doesn't support English
    if effective_lang is None or effective_lang == "en" or effective_lang not in INDIC_CONFORMER_LANGUAGE_MAP:
        return {
            "text": "",
            "language": effective_lang or "en",
            "use_browser_stt": True,
            "duration_seconds": 0.0,
        }

    conformer_lang = INDIC_CONFORMER_LANGUAGE_MAP[effective_lang]

    try:
        model = _get_indic_conformer_model()
        wav_tensor = _audio_bytes_to_tensor(audio_bytes)

        start = time.monotonic()
        decode_strategy = settings.indic_conformer_decode_strategy  # "ctc" or "rnnt"
        transcription = model(wav_tensor, conformer_lang, decode_strategy)

        elapsed = time.monotonic() - start

        # The model returns a string directly
        text = str(transcription).strip() if transcription else ""

        return {
            "text": text,
            "language": effective_lang,
            "duration_seconds": round(elapsed, 2),
            "use_browser_stt": False,
        }
    except VoiceServiceError:
        raise
    except Exception as exc:
        logger.exception("Indic Conformer transcription failed: %s", exc)
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
