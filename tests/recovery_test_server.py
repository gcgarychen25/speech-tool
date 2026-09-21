"""Isolated synthetic browser fixture. Never points at the real event store."""
import tempfile
from pathlib import Path
import uvicorn
from speech_tool.app import create_app
from speech_tool.store import EventStore
from speech_tool.pipeline import Pipeline
from speech_tool.polish import PassthroughPolisher
from tests.fakes import FakeAsr

with tempfile.TemporaryDirectory(prefix='speech-browser-fixture-') as directory:
    store = EventStore(Path(directory))
    pipe = Pipeline(store, asr=FakeAsr(), polisher=PassthroughPolisher())
    app = create_app(store, pipe)
    uvicorn.run(app, host='127.0.0.1', port=8879, log_level='warning')
