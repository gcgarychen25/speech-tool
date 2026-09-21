from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import time
from pathlib import Path

from speech_tool.config import data_dir


def pid_path() -> Path:
    path = data_dir() / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path / "server.pid"


def pids_listening(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    for line in result.stdout.split():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid > 0 and pid != os.getpid() and pid not in pids:
            pids.append(pid)
    return pids


def pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_pid(pid: int, timeout: float = 1.5) -> None:
    if not pid_alive(pid):
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            return
        deadline = time.time() + (timeout if sig == signal.SIGTERM else 0.5)
        while time.time() < deadline:
            if not pid_alive(pid):
                return
            time.sleep(0.05)


def replace_existing(port: int) -> list[int]:
    lock_path = pid_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    killed: list[int] = []
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        victims: list[int] = []
        handle.seek(0)
        raw = handle.read().strip()
        if raw.isdigit() and pid_alive(int(raw)):
            victims.append(int(raw))
        for pid in pids_listening(port):
            if pid not in victims:
                victims.append(pid)
        for pid in victims:
            terminate_pid(pid)
            killed.append(pid)
        wait_port_free(port)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())
    return killed


def clear_pid_file() -> None:
    path = pid_path()
    if not path.exists():
        return
    try:
        current = int(path.read_text().strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return
    if current == os.getpid():
        path.unlink(missing_ok=True)


def wait_port_free(port: int, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        listeners = pids_listening(port)
        if not listeners:
            return
        for pid in listeners:
            terminate_pid(pid)
        time.sleep(0.05)
    still = pids_listening(port)
    raise RuntimeError(
        f"Port {port} is still in use after stopping the previous instance: {still}"
    )


def wait_healthy(port: int, timeout: float = 20.0) -> None:
    import urllib.request

    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Server did not become healthy on port {port}: {last_error}")
