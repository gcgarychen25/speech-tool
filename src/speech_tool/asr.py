from __future__ import annotations

import importlib.metadata
import os
import time
from dataclasses import dataclass
from pathlib import Path

from speech_tool.config import DEFAULT_ASR_MODEL
from speech_tool.lexicon import whisper_initial_prompt
from speech_tool.media import ensure_wav_16k
from speech_tool.textnorm import to_simplified


@dataclass
class AsrResult:
    text: str
    model: str
    version: str
    elapsed_seconds: float
    rtf: float


class AsrBackend:
    def transcribe(self, audio_path: Path, *, kind: str | None = None) -> AsrResult:
        raise NotImplementedError


class FailingAsr(AsrBackend):
    def transcribe(self, audio_path: Path, *, kind: str | None = None) -> AsrResult:
        raise RuntimeError("Injected ASR failure")


class MlxWhisperAsr(AsrBackend):
    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_ASR_MODEL
        self._warm = False

    def warmup(self) -> None:
        import numpy as np

        silence = np.zeros(16000, dtype=np.float32)
        self._transcribe_array(silence)
        self._warm = True

    def transcribe(self, audio_path: Path, *, kind: str | None = None, course: str | None = None) -> AsrResult:
        try:
            import mlx_whisper  # noqa: F401
        except Exception as exc:
            raise RuntimeError(
                "mlx-whisper is not available. Install with: pip install mlx-whisper"
            ) from exc

        started = time.perf_counter()
        wav = audio_path.with_suffix(".asr.wav")
        cleanup = None
        if audio_path.suffix.lower() != ".wav":
            ensure_wav_16k(audio_path, wav)
            work = wav
            cleanup = wav
        else:
            work = audio_path
        out = self._run(str(work), kind=kind, course=course)
        elapsed = time.perf_counter() - started
        if cleanup and cleanup.exists():
            cleanup.unlink(missing_ok=True)
        return self._to_result(out, elapsed)

    def _transcribe_array(self, audio, *, kind: str | None = None) -> AsrResult:
        started = time.perf_counter()
        out = self._run(audio, kind=kind)
        elapsed = time.perf_counter() - started
        return self._to_result(out, elapsed)

    def _run(self, audio, *, kind: str | None = None, course: str | None = None):
        import mlx_whisper

        return mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model,
            word_timestamps=False,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            initial_prompt=whisper_initial_prompt(kind, course) or None,
            verbose=None,
        )

    def _to_result(self, out: dict, elapsed: float) -> AsrResult:
        text = to_simplified((out.get("text") or "").strip())
        duration = 0.0
        for segment in out.get("segments") or []:
            duration = max(duration, float(segment.get("end") or 0))
        rtf = elapsed / duration if duration > 0 else elapsed
        version = _pkg_version("mlx-whisper")
        return AsrResult(
            text=text,
            model=self.model,
            version=version,
            elapsed_seconds=elapsed,
            rtf=rtf,
        )


def _pkg_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def default_asr() -> AsrBackend:
    kind = os.environ.get("SPEECH_TOOL_ASR_BACKEND", "mlx")
    if kind == "fail":
        return FailingAsr()
    return MlxWhisperAsr()
