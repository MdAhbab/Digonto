"""Speech to text for the Interview Room, on the same local model as
everything else.

**How audio actually reaches Gemma 4 E2B through Ollama, and how that was
determined.** `GET /api/show` for `gemma4:e2b` on this deployment reports
`capabilities: [completion, vision, audio, tools, thinking]`, and the GGUF
carries a `gemma4.audio.*` tower. Ollama 0.32.4's `/api/chat` was then probed
with the same 4.6 second recording three ways:

  * a message-level `"audio": [<base64>]` array: HTTP 200, and the reply was
    byte for byte identical to a control run with no media attached at all,
    i.e. the field is accepted by the JSON decoder and then silently ignored;
  * a `content` array of typed parts (`input_audio`): HTTP 400,
    `json: cannot unmarshal array into Go struct field
    ChatRequest.messages.content of type string`;
  * a message-level `"images": [<base64>]` array: HTTP 200 and an exact
    transcript.

So on this build there is one media channel, `message.images`, and the server
sniffs what it was handed rather than trusting a declared kind. That is what
this module uses. The same probe showed which containers that channel can
decode: WAV (PCM) and FLAC work; AAC in either an ADTS or an MP4/M4A
container is refused with `Failed to load image or audio file`. WebM/Opus,
which is what a browser's `MediaRecorder` produces by default, is in that
second group, which is why the client converts to 16 kHz mono WAV before it
sends anything (see frontend Interview.tsx).

**Why an acoustic gate exists before the model is ever asked.** Handed one
second of digital silence, the model answered `"I don't know"` with
`confidence: 0.98`. A transcript of words nobody said is worse than no
transcript at all: it goes into an interview answer, gets scored, and the
student is told they said something they did not. So a WAV that is too short
or too quiet is rejected here, in Python, on measured sample values, and the
model is never asked. The confidence this module returns is the model's own
self-report, clamped: it is a usable signal for "was this clear", not an
acoustic posterior, and it is documented as such wherever it surfaces.
"""

from __future__ import annotations

import array
import base64
import json
import logging
import math
import struct
from typing import Any, Final, TypedDict

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class Transcript(TypedDict):
    """What `transcribe` returns.

    `text` and `confidence` are the contract. `available` is False when the
    voice path itself is unusable in this deployment (no audio-capable model,
    a container the runtime cannot decode, Ollama unreachable); it is True
    with an empty `text` when the recording was fine but nothing intelligible
    was in it. `detail_en`/`detail_bn` say which, in the student's language.
    """

    text: str
    confidence: float
    available: bool
    detail_en: str
    detail_bn: str


# Minimum recording the model is allowed to see at all.
_MIN_DURATION_S: Final[float] = 0.35
# Full-scale RMS below which a 16-bit PCM recording counts as silence. A quiet
# room mic floor sits near 0.002; ordinary speech at arm's length is 0.02 and
# up. 0.004 sits between them without cutting off a soft speaker.
_MIN_RMS: Final[float] = 0.004
_MAX_AUDIO_BYTES: Final[int] = 16 * 1024 * 1024

_TRANSCRIBE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "audible": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["text", "audible", "confidence"],
}

_SYSTEM: Final[str] = (
    "You transcribe short spoken answers from Bangladeshi students practising "
    "for a visa interview. Write exactly what was said, in the language it was "
    "spoken, mixing Bangla and English in the same sentence if that is what you "
    "heard. Do not translate, do not correct grammar, do not add or complete "
    "words, and do not answer the question the speaker is answering. If the "
    "recording carries no intelligible speech, return an empty text and set "
    "audible to false. Return JSON only."
)

_LANG_HINT: Final[dict[str, str]] = {
    "bn": "The speaker is most likely speaking Bangla, possibly with English words mixed in.",
    "en": "The speaker is most likely speaking English, possibly with Bangla words mixed in.",
}

_UNAVAILABLE_EN: Final[str] = (
    "Voice answers are not available right now, so nothing was recorded as your "
    "answer. Please type it instead."
)
_UNAVAILABLE_BN: Final[str] = (
    "এই মুহূর্তে ভয়েসে উত্তর দেওয়া যাচ্ছে না, তাই কিছুই রেকর্ড হয়নি। অনুগ্রহ করে "
    "লিখে উত্তর দিন।"
)

_client: httpx.AsyncClient | None = None
_audio_capable: bool | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=180.0)
    return _client


async def aclose() -> None:
    """Release the module's HTTP client. Called from the app lifespan if the
    process is shutting down; safe to call when nothing was ever opened."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _unavailable(detail_en: str, detail_bn: str) -> Transcript:
    return {
        "text": "",
        "confidence": 0.0,
        "available": False,
        "detail_en": detail_en,
        "detail_bn": detail_bn,
    }


def _nothing_heard(detail_en: str, detail_bn: str) -> Transcript:
    return {
        "text": "",
        "confidence": 0.0,
        "available": True,
        "detail_en": detail_en,
        "detail_bn": detail_bn,
    }


# --- container sniffing ------------------------------------------------------


def sniff_audio(data: bytes) -> str | None:
    """The real container of `data`, from its leading bytes.

    The browser's declared MIME type is a hint; what the local runtime can
    decode depends on the actual bytes.
    """
    if len(data) < 12:
        return None
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data.startswith(b"ID3") or (data[0] == 0xFF and (data[1] & 0xE6) == 0xE2):
        return "audio/mpeg"
    return None


# --- WAV inspection ----------------------------------------------------------


class _Wav(TypedDict):
    channels: int
    sample_rate: int
    bits: int
    format_code: int
    data_offset: int
    data_length: int


def _parse_wav(data: bytes) -> _Wav | None:
    """Locate the `fmt ` and `data` chunks. Tolerates a truncated `data`
    chunk, which is exactly what a recording still being streamed looks
    like."""
    if len(data) < 12 or not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        return None
    pos = 12
    fmt: tuple[int, int, int, int] | None = None
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        (chunk_size,) = struct.unpack_from("<I", data, pos + 4)
        body = pos + 8
        if chunk_id == b"fmt " and body + 16 <= len(data):
            format_code, channels, sample_rate, _byte_rate, _align, bits = struct.unpack_from(
                "<HHIIHH", data, body
            )
            fmt = (format_code, channels, sample_rate, bits)
        elif chunk_id == b"data":
            if fmt is None:
                return None
            available = min(chunk_size, len(data) - body)
            return {
                "format_code": fmt[0],
                "channels": fmt[1] or 1,
                "sample_rate": fmt[2] or 16000,
                "bits": fmt[3] or 16,
                "data_offset": body,
                "data_length": max(0, available),
            }
        pos = body + chunk_size + (chunk_size & 1)
    return None


def wav_prefix(data: bytes) -> bytes | None:
    """A truncated WAV made playable again, or None if it is not a WAV.

    The interview socket transcribes what has arrived so far to produce
    `transcript.partial` while the student is still speaking. A WAV whose
    header still advertises the full recording length is rejected by decoders,
    so the two length fields are rewritten to describe the bytes that are
    actually present. Nothing is invented: the samples are the ones already
    received.
    """
    parsed = _parse_wav(data)
    if parsed is None:
        return None
    end = parsed["data_offset"] + parsed["data_length"]
    out = bytearray(data[:end])
    struct.pack_into("<I", out, 4, max(0, len(out) - 8))
    struct.pack_into("<I", out, parsed["data_offset"] - 4, parsed["data_length"])
    return bytes(out)


def wav_level(data: bytes) -> tuple[float, float] | None:
    """(duration in seconds, full-scale RMS) for 16-bit PCM, else None.

    None means "not measurable here", not "silent": a FLAC or MP3 upload is
    passed through to the model without this gate rather than being refused
    for a property that could not be checked.
    """
    parsed = _parse_wav(data)
    if parsed is None or parsed["format_code"] != 1 or parsed["bits"] != 16:
        return None
    frame_bytes = 2 * parsed["channels"]
    usable = (parsed["data_length"] // frame_bytes) * frame_bytes
    if usable <= 0:
        return 0.0, 0.0
    samples = array.array("h")
    samples.frombytes(data[parsed["data_offset"] : parsed["data_offset"] + usable])
    if sys_is_big_endian():
        samples.byteswap()
    duration = usable / (frame_bytes * parsed["sample_rate"])
    total = 0
    for sample in samples:
        total += sample * sample
    rms = math.sqrt(total / len(samples)) / 32768.0
    return duration, rms


def sys_is_big_endian() -> bool:
    """WAV samples are little endian on the wire; `array` uses host order."""
    return struct.pack("=H", 1) != struct.pack("<H", 1)


# --- capability probe --------------------------------------------------------


async def model_can_hear(settings: Settings | None = None) -> bool:
    """Whether the served model declares the `audio` capability.

    Cached after the first successful answer: it is a property of the loaded
    model, and asking on every utterance would add a round trip to each one.
    """
    global _audio_capable
    if _audio_capable is not None:
        return _audio_capable
    s = settings or get_settings()
    try:
        response = await _http().post(
            f"{s.ollama_base_url}/api/show", json={"model": s.gemma_model}, timeout=10.0
        )
        response.raise_for_status()
        capabilities = response.json().get("capabilities") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("could not read model capabilities: %s", exc)
        return False
    _audio_capable = "audio" in capabilities
    if not _audio_capable:
        log.warning(
            "model %s does not declare the audio capability; voice input is off", s.gemma_model
        )
    return _audio_capable


# --- the one public entry point ---------------------------------------------


async def transcribe(
    audio_bytes: bytes,
    mime_type: str,
    lang_hint: str = "bn",
    *,
    settings: Settings | None = None,
) -> Transcript:
    """Transcribe one recorded answer on the local model.

    Never returns words the audio did not contain: every path that cannot
    produce a real transcript returns an empty `text` with a bilingual reason.
    """
    s = settings or get_settings()

    if not audio_bytes:
        return _nothing_heard(
            "Nothing was recorded. Check that the microphone is not muted and try again.",
            "কিছুই রেকর্ড হয়নি। মাইক্রোফোন বন্ধ আছে কি না দেখে আবার চেষ্টা করুন।",
        )
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        return _nothing_heard(
            "That recording is too long. Answer in under two minutes and try again.",
            "রেকর্ডিংটি অনেক লম্বা। দুই মিনিটের মধ্যে উত্তর দিয়ে আবার চেষ্টা করুন।",
        )

    container = sniff_audio(audio_bytes) or mime_type
    if not container.startswith("audio/"):
        return _unavailable(_UNAVAILABLE_EN, _UNAVAILABLE_BN)

    level = wav_level(audio_bytes)
    if level is not None:
        duration, rms = level
        if duration < _MIN_DURATION_S:
            return _nothing_heard(
                "That recording was too short to make out. Hold the button while you speak.",
                "রেকর্ডিংটি এত ছোট যে কিছু বোঝা যায়নি। কথা বলার সময় বোতামটি চেপে ধরে রাখুন।",
            )
        if rms < _MIN_RMS:
            return _nothing_heard(
                "No speech was audible in that recording. Move closer to the microphone "
                "and try again.",
                "এই রেকর্ডিংয়ে কোনো কথা শোনা যায়নি। মাইক্রোফোনের কাছে গিয়ে আবার চেষ্টা করুন।",
            )

    if not await model_can_hear(s):
        return _unavailable(
            "The local model in this deployment cannot listen to audio, so voice "
            "answers are off. Please type your answer.",
            "এই ডিপ্লয়মেন্টের স্থানীয় মডেলটি অডিও শুনতে পারে না, তাই ভয়েসে উত্তর দেওয়া বন্ধ। "
            "অনুগ্রহ করে লিখে উত্তর দিন।",
        )

    body = {
        "model": s.gemma_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    "Transcribe this recording. "
                    + _LANG_HINT.get(lang_hint, _LANG_HINT["bn"])
                ),
                # The one media channel this Ollama build honours; see the
                # module docstring for the probe that established it.
                "images": [base64.b64encode(audio_bytes).decode("ascii")],
            },
        ],
        "format": _TRANSCRIBE_SCHEMA,
        "options": {"temperature": 0.0, "num_predict": 640},
        "think": False,
        "keep_alive": s.ollama_keep_alive,
    }

    try:
        response = await _http().post(f"{s.ollama_base_url}/api/chat", json=body)
    except httpx.HTTPError as exc:
        log.warning("speech: ollama unreachable: %s", exc)
        return _unavailable(_UNAVAILABLE_EN, _UNAVAILABLE_BN)

    if response.status_code == 400:
        # What the runtime says when it cannot decode the container it was
        # handed (verified with AAC and M4A). Not a server fault, and not
        # something a retry fixes.
        log.warning("speech: runtime refused container=%s body=%s", container, response.text[:200])
        return _unavailable(
            "This device's recording format cannot be read by the local model. "
            "Please type your answer instead.",
            "এই ডিভাইসের রেকর্ডিং ফরম্যাট স্থানীয় মডেল পড়তে পারছে না। অনুগ্রহ করে লিখে "
            "উত্তর দিন।",
        )
    if response.status_code != 200:
        log.warning("speech: ollama returned %s", response.status_code)
        return _unavailable(_UNAVAILABLE_EN, _UNAVAILABLE_BN)

    content = (response.json().get("message") or {}).get("content") or ""
    try:
        parsed = json.loads(content)
    except ValueError:
        log.warning("speech: model reply was not JSON")
        return _unavailable(_UNAVAILABLE_EN, _UNAVAILABLE_BN)

    text = " ".join(str(parsed.get("text", "")).split())
    audible = bool(parsed.get("audible", True))
    try:
        confidence = min(1.0, max(0.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    if not text or not audible:
        return _nothing_heard(
            "Nothing intelligible was heard in that recording. Try again, or type "
            "your answer.",
            "এই রেকর্ডিংয়ে বোধগম্য কিছু শোনা যায়নি। আবার চেষ্টা করুন, অথবা লিখে উত্তর দিন।",
        )

    return {
        "text": text,
        "confidence": confidence,
        "available": True,
        "detail_en": "",
        "detail_bn": "",
    }
