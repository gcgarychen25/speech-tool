from pathlib import Path

from speech_tool.asr import AsrBackend, AsrResult


class FakeAsr(AsrBackend):
    def transcribe(self, audio_path: Path, *, kind: str | None = None) -> AsrResult:
        return AsrResult(
            text="hello world from asr",
            model="fake",
            version="test",
            elapsed_seconds=0.01,
            rtf=0.01,
        )
