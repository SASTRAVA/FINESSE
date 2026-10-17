"""
JARVIS premium voice — natural TTS when an API key is set, else None (the browser
falls back to speechSynthesis).

Add ONE key to .env and JARVIS instantly sounds real:
  OPENAI_API_KEY=sk-...          -> OpenAI gpt-4o-mini-tts, voice "onyx" (deep male)
  ELEVENLABS_API_KEY=...         -> ElevenLabs turbo, British male "Daniel" (most JARVIS)

Returns mp3 bytes the /api/tts endpoint streams to the dashboard's <audio>.
"""
from __future__ import annotations

from .config import cfg
from .llm.provider import ensure_external_egress_allowed, scrub_outbound

_OPENAI_URL = "https://api.openai.com/v1/audio/speech"
_ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{vid}"


def provider() -> str:
    return cfg.voice_provider


async def synth(text: str, *, sensitivity: str = "confidential") -> tuple[bytes, str] | None:
    """(mp3_bytes, mime) from the configured provider, or None to use the browser voice."""
    ensure_external_egress_allowed(sensitivity, "TTS")
    text = (text or "").strip()[:4000]
    if not text:
        return None
    text = scrub_outbound(text, redact_pii=cfg.REDACT_PII_ON_EXTERNAL_LLM)
    import httpx
    p = provider()
    try:
        if p == "openai":
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(_OPENAI_URL,
                                 headers={"Authorization": f"Bearer {cfg.OPENAI_API_KEY}"},
                                 json={"model": cfg.OPENAI_TTS_MODEL, "voice": cfg.OPENAI_TTS_VOICE,
                                       "input": text, "response_format": "mp3"})
            if r.status_code == 200:
                return r.content, "audio/mpeg"
        elif p == "elevenlabs":
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(_ELEVEN_URL.format(vid=cfg.ELEVENLABS_VOICE_ID),
                                 headers={"xi-api-key": cfg.ELEVENLABS_API_KEY,
                                          "accept": "audio/mpeg"},
                                 json={"text": text, "model_id": cfg.ELEVENLABS_MODEL,
                                       "voice_settings": {"stability": 0.45,
                                                          "similarity_boost": 0.8}})
            if r.status_code == 200:
                return r.content, "audio/mpeg"
        elif p == "edge":                       # FREE Microsoft neural voice, no key
            import edge_tts
            communicate = edge_tts.Communicate(text, cfg.EDGE_VOICE)
            buf = b""
            async for ch in communicate.stream():
                if ch["type"] == "audio":
                    buf += ch["data"]
            if buf:
                return buf, "audio/mpeg"
    except Exception:  # noqa: BLE001 — any failure -> browser fallback, never crash the reply
        return None
    return None
