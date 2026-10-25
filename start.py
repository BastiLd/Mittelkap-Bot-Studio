"""One Homelab Manager profile, three supervised processes. No shell execution."""
from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

COMPONENTS = ("Jarvis", "Ultron", "Dashboard")
SERVICE_MODES = {"all": COMPONENTS, "jarvis": ("Jarvis", "Dashboard"), "ultron": ("Ultron",)}
BOT_KEYS = ("DISCORD_TOKEN", "YOUTUBE_API_KEY", "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET",
            "TIKTOK_ACCESS_TOKEN", "TIKTOK_REFRESH_TOKEN", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
PREFIXES = ("JARVIS_", "ULTRON_")
DEPENDENCIES = ("discord.py", "aiohttp", "Pillow", "python-dotenv", "tzdata", "defusedxml")
SYSTEM_KEYS = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "VIRTUAL_ENV", "LD_LIBRARY_PATH",
               "TMP", "TEMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}


def workspace():
    folder = Path(__file__).resolve().parent
    return folder if (folder / "Jarvis").is_dir() else folder.parent


def component_dir(root, name):
    folder = Path(root) / name
    if name == "Dashboard" and not folder.is_dir():
        return Path(root) / "Webseite"
    return folder


def environments(root, original, mode="all"):
    """Only the corresponding bot gets its token; dashboard receives no bot credentials."""
    root = Path(root).resolve()
    selected = SERVICE_MODES[mode]
    for component in selected:
        entry = "server.py" if component == "Dashboard" else "bot.py"
        if not (component_dir(root, component) / entry).is_file():
            raise ValueError(f"Paket unvollständig: {component}/{entry} fehlt.")
    required = [component.upper() + "_DISCORD_TOKEN" for component in selected if component != "Dashboard"]
    if "Dashboard" in selected:
        required.append("DASHBOARD_PUBLIC_URL")
    if mode == "ultron":
        required.append("DCBOTS_DASHBOARD_DIR")
    missing = [name for name in required
               if not original.get(name, "").strip()]
    if missing:
        raise ValueError("Im Manager unter Environment eintragen: " + ", ".join(missing))
    control = Path(original.get("DCBOTS_DASHBOARD_DIR", str(root / "private-control")))
    if not control.is_absolute() or control == Path(control.anchor):
        raise ValueError("DCBOTS_DASHBOARD_DIR muss ein absoluter privater Verzeichnispfad sein, nicht die Dateisystemwurzel.")
    if "Dashboard" in selected:
        public = urlsplit(original["DASHBOARD_PUBLIC_URL"].strip())
        if public.scheme not in {"http", "https"} or not public.hostname or public.username or public.password or public.path not in {"", "/"} or public.query or public.fragment:
            raise ValueError("DASHBOARD_PUBLIC_URL muss die genaue Browser-Basisadresse ohne Unterpfad enthalten.")
        try:
            port = int(original.get("DASHBOARD_PORT", "8765"))
            if not 1024 <= port <= 65535:
                raise ValueError()
        except ValueError:
            raise ValueError("DASHBOARD_PORT muss zwischen 1024 und 65535 liegen.") from None
    # Manager UI passwords and credentials of other applications must not reach any child.
    common = {key: value for key, value in original.items() if key.upper() in SYSTEM_KEYS or key.startswith("LC_")}
    common.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", TZ="Europe/Vienna",
                  DCBOTS_DASHBOARD_DIR=str(control),
                  DCBOTS_STATE_DIR=str(root / "private-runtime"),
                  DCBOTS_SECRETS_DIR=str(root / "private-secrets"))
    result = {}
    for component in selected:
        env = dict(common)
        if component == "Dashboard":
            env.update(DASHBOARD_HOST=original.get("DASHBOARD_HOST", "0.0.0.0"),
                       DASHBOARD_PORT=str(port), DASHBOARD_PUBLIC_URL=original["DASHBOARD_PUBLIC_URL"].strip())
            if original.get("DASHBOARD_SETUP_KEY"):
                env["DASHBOARD_SETUP_KEY"] = original["DASHBOARD_SETUP_KEY"]
        else:
            for key in BOT_KEYS:
                value = original.get(component.upper() + "_" + key, "").strip()
                if value:
                    env[key] = value
        result[component] = env
    return result


def sensitive_values(original):
    return sorted({value for key, value in original.items() if value and
                   (key in BOT_KEYS or key == "DASHBOARD_SETUP_KEY" or
                    (key.startswith(PREFIXES) and any(word in key for word in ("TOKEN", "SECRET", "KEY"))))}, key=len, reverse=True)


def pump_output(label, process, values):
    try:
        for line in process.stdout:
            for value in values:
                line = line.replace(value, "[VERDECKT]")
            print(f"[{label}] {line.rstrip()}", flush=True)
    except (OSError, ValueError):
        pass


def request_exit(process, force=False):
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            # Every child owns its own process group. SIGINT lets asyncio close Discord cleanly.
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGINT)
        elif force:
            process.kill()
        else:
            process.terminate()
    except (ProcessLookupError, OSError):
        pass


def stop_children(processes, timeout=7.0):
    for process in processes.values():
        request_exit(process)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(p.poll() is None for p in processes.values()):
        time.sleep(.1)
    for process in processes.values():
        request_exit(process, force=True)
    for process in processes.values():
        try:
            process.wait(timeout=.3)
        except subprocess.TimeoutExpired:
            pass


def run(root, envs, values):
    stop = threading.Event()
    processes = {}
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    result = 0
    try:
        for label in envs:
            if stop.is_set():
                break
            args = [sys.executable, "-u", "server.py"] if label == "Dashboard" else [sys.executable, "-u", "bot.py", "--run"]
            process = subprocess.Popen(args, cwd=component_dir(root, label), env=envs[label], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", start_new_session=os.name == "posix")
            processes[label] = process
            threading.Thread(target=pump_output, args=(label, process, values), daemon=True).start()
            print(f"[Start] {label}: Prozess gestartet; Online-Status wird von der Anwendung gemeldet.", flush=True)
        while not stop.wait(.2):
            for label, process in processes.items():
                code = process.poll()
                if code is not None:
                    print(f"[Supervisor] {label} wurde beendet (Code {code}). Alle Dienste werden kontrolliert beendet.", flush=True)
                    result = code if code > 0 else 1
                    stop.set()
                    break
    finally:
        print("[Supervisor] Alle Dienste werden beendet …", flush=True)
        stop_children(processes)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return result


def main():
    parser = argparse.ArgumentParser(description="Mittelkap: Jarvis, Ultron und Dashboard gemeinsam steuern.")
    parser.add_argument("--check", action="store_true", help="Nur Paket, Environment und Bibliotheken prüfen; keine Prozesse, kein Netzwerk.")
    parser.add_argument("--services", choices=SERVICE_MODES, default="all", help="jarvis: Jarvis + Dashboard; ultron: nur Ultron mit gemeinsamer Datenablage; all: alle drei.")
    args = parser.parse_args()
    root = workspace()
    try:
        envs = environments(root, os.environ, args.services)
        for name in DEPENDENCIES:
            importlib.metadata.version(name)
        if args.check:
            print("Paket, Variablennamen und Bibliotheken geprüft. Kein Bot wurde gestartet; keine Tokenwerte ausgegeben.")
            return 0
        control = Path(next(iter(envs.values()))["DCBOTS_DASHBOARD_DIR"])
        for path in (control, root / "private-runtime", root / "private-secrets"):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "posix":
                path.chmod(0o700)
        for component in (name for name in envs if name != "Dashboard"):
            (root / component / "data").mkdir(exist_ok=True)
        return run(root, envs, sensitive_values(os.environ))
    except (ValueError, OSError, importlib.metadata.PackageNotFoundError) as exc:
        # Never print an exception originating from a child environment or a token value.
        if isinstance(exc, ValueError):
            message = str(exc)
        elif isinstance(exc, importlib.metadata.PackageNotFoundError):
            message = "Bibliotheken fehlen. Im Manager zuerst requirements.txt installieren."
        else:
            message = "Datei oder Prozess konnte nicht geöffnet werden. Paket und Schreibrechte des Workspaces prüfen."
        print("Startprüfung fehlgeschlagen: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
