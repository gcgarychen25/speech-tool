from __future__ import annotations

import argparse
import atexit
import logging
import os
import sys
import threading

import uvicorn

from speech_tool.app import create_app
from speech_tool.browser import activate_browser
from speech_tool.config import DEFAULT_PORT, data_dir
from speech_tool.pipeline import Pipeline
from speech_tool.runtime import clear_pid_file, replace_existing, wait_healthy
from speech_tool.store import EventStore

log = logging.getLogger("speech_tool")


def _install_signals() -> None:
    atexit.register(clear_pid_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Speech Tool")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve"])
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SPEECH_TOOL_PORT", DEFAULT_PORT)),
    )
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument(
        "--no-replace",
        action="store_true",
        help="Fail if another instance is already running instead of replacing it",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.data_dir:
        os.environ["SPEECH_TOOL_DATA_DIR"] = args.data_dir

    _install_signals()
    if args.no_replace:
        from speech_tool.runtime import pids_listening

        existing = pids_listening(args.port)
        if existing:
            print(f"Already running on port {args.port}: {existing}", file=sys.stderr)
            raise SystemExit(1)
    else:
        killed = replace_existing(args.port)
        if killed:
            log.info("Replaced previous instance(s): %s", killed)

    store = EventStore(data_dir())
    pipeline = Pipeline(store, auto_start=True)
    if not args.no_warmup:
        # Use the same executor as transcription: no simultaneous model loads,
        # and HTTP capture becomes available before the model is ready.
        pipeline._asr_pool.submit(pipeline.warmup_asr)
    app = create_app(store, pipeline)

    if not args.no_open:
        def _open() -> None:
            try:
                wait_healthy(args.port)
                activate_browser(args.port)
            except Exception:
                log.exception("Could not open the browser")

        threading.Thread(target=_open, daemon=True).start()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
        timeout_graceful_shutdown=1,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
