"""Local process state and cooperative shutdown; contains no credentials."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from pathlib import Path


def runtime_dir(root: Path) -> Path:
    # Machine-local: another Nextcloud computer must never control this process.
    # AppData is virtualized in MSIX-packaged hosts (e.g. Codex). Use a real
    # per-user directory so Explorer-launched controllers share the same state.
    base = Path(os.environ.get("DCBOTS_STATE_DIR", str(Path.home() / ".mittelkap" / "dcbots" / "runtime"))).expanduser()
    if not base.is_absolute():
        raise ValueError("DCBOTS_STATE_DIR muss ein absoluter Pfad sein.")
    import hashlib
    key = hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()[:16]
    path = base / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(path: Path, data: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


async def run_client(client, token: str, root: Path):
    folder = runtime_dir(root)
    state_file, stop_file = folder / "state.json", folder / "stop.json"
    identity = uuid.uuid4().hex
    state = {"pid": os.getpid(), "instance": identity, "host": socket.gethostname(), "state": "starting"}

    def save(status):
        state.update(state=status, updated=time.time())
        write_state(state_file, state)

    save("starting")
    stopped = False
    login = None

    async def watch():
        nonlocal stopped
        while True:
            request = read_state(stop_file)
            if request.get("instance") == identity:
                stopped = True
                save("stopping")
                if login is not None:
                    login.cancel()
                return
            status = "online" if client.is_ready() else "connecting"
            if state["state"] != status:
                save(status)
            await asyncio.sleep(.25)

    try:
        async with client:
            login = asyncio.create_task(client.start(token))
            watcher = asyncio.create_task(watch())
            try:
                await login
            except asyncio.CancelledError:
                if not stopped:
                    raise
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
    finally:
        save("stopped")
        if read_state(stop_file).get("instance") == identity:
            stop_file.unlink(missing_ok=True)
