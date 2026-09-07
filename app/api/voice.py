import base64
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas.envelope import success_response
from app.services.voice_service import transcribe_audio, synthesize_speech, VoiceServiceError
from app.utils.trace import trace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["Voice API"])


class TranscribeRequest(BaseModel):
    # Base64-encoded audio bytes (webm/wav/ogg from the browser's MediaRecorder).
    audio_base64: str = Field(..., min_length=1)
    language: str = "en"


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    language: str = "en"


@router.post("/transcribe")
@trace
def voice_transcribe(request: TranscribeRequest):
    try:
        audio_bytes = base64.b64decode(request.audio_base64)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="audio_base64 is not valid base64") from exc

    try:
        result = transcribe_audio(audio_bytes, language=request.language)
    except VoiceServiceError as exc:
        logger.warning("Voice transcription unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected voice transcription error: %s", exc)
        raise HTTPException(status_code=500, detail="Transcription failed") from exc

    return success_response(result, "Transcription complete")


@router.post("/synthesize")
@trace
def voice_synthesize(request: SynthesizeRequest):
    result = synthesize_speech(request.text, language=request.language)
    if result.get("used_fallback"):
        # Not an error: this tells the frontend to speak `text` via the
        # browser's own SpeechSynthesis API instead. Still a 200 - the
        # request succeeded, it just couldn't produce Indic Parler audio
        # in time.
        return success_response(
            {"audio_base64": None, "used_fallback": True, "text": result["text"]},
            "Falling back to browser speech synthesis",
        )

    return success_response(
        {
            "audio_base64": base64.b64encode(result["audio_bytes"]).decode("ascii"),
            "sample_rate": result["sample_rate"],
            "used_fallback": False,
        },
        "Speech synthesized",
    )
