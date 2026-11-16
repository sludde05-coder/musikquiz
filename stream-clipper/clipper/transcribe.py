"""Speech-to-text with word timestamps (faster-whisper, runs locally on CPU or GPU).

Optional: if faster-whisper isn't installed, clips get no speech captions.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
_models: dict[str, object] = {}
_lock = threading.Lock()


@dataclass
class Word:
    start: float
    end: float
    text: str


def transcribe(path: Path, model_size: str = "small") -> list[Word]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("faster-whisper not installed: no speech captions (pip install faster-whisper)")
        return []
    with _lock:  # one model per size, shared, and whisper isn't thread-safe
        try:
            if model_size not in _models:
                log.info("loading whisper model %r (first time downloads it)", model_size)
                _models[model_size] = WhisperModel(model_size, device="auto", compute_type="int8")
            segments, _ = _models[model_size].transcribe(str(path), word_timestamps=True, vad_filter=True)
            return [Word(w.start, w.end, w.word.strip())
                    for seg in segments for w in (seg.words or []) if w.word.strip()]
        except Exception as e:  # noqa: BLE001 - captions are a bonus; never lose the clip over them
            log.warning("transcription failed (%s): no speech captions for %s", e, path.name)
            return []
