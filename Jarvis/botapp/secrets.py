from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def private_env_path(persona: str) -> Path:
    if persona not in {"jarvis", "ultron"}:
        raise ValueError("Unbekannter Bot für die Token-Datei.")
    explicit = os.getenv("DCBOTS_SECRETS_DIR")
    if explicit:
        folder = Path(explicit).expanduser()
        if not folder.is_absolute():
            raise ValueError("DCBOTS_SECRETS_DIR muss ein absoluter Pfad sein.")
    elif os.name == "nt":
        # MSIX applications can redirect AppData into their package sandbox.
        # A normal user-profile directory is shared with Explorer/CMD launches.
        # Do not silently fall back to AppData: that recreates two token sources.
        folder = Path.home() / ".mittelkap" / "dcbots" / "secrets"
    else:
        folder = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mittelkap" / "dcbots" / "secrets"
    return folder / f"{persona.title()}.env"


def credentials_file(root: Path, persona: str) -> Path:
    private = private_env_path(persona)
    # If both files are absent, report the intended private path, not a misleading
    # project .env. Never move or copy credentials into the synchronized project.
    return private if private.is_file() or not (root / ".env").is_file() else root / ".env"


def load_credentials(root: Path, persona: str) -> Path:
    selected = credentials_file(root, persona)
    # Nonempty deployment variables win; empty inherited variables must not hide
    # credentials entered in the private file. UTF-8 BOM is common in Windows editors.
    for key, value in dotenv_values(selected, encoding="utf-8-sig").items():
        if value is not None and not os.environ.get(key, "").strip():
            os.environ[key] = value
    return selected


def credential_diagnostics(root: Path, persona: str) -> dict:
    """Read-only metadata; never return file contents, key lists, values or hashes.

    The exact file selected by the loader is inspected with stat and open. In
    particular, a missing file and an empty/missing DISCORD_TOKEN are distinct.
    Unlike load_credentials this function never adds file values to os.environ.
    """
    from datetime import datetime, timezone
    import getpass
    from io import StringIO
    import socket
    import stat
    import sys
    from dotenv.parser import parse_stream
    from dotenv.main import resolve_variables

    environment_present = bool(os.environ.get("DISCORD_TOKEN", "").strip())
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "pid": os.getpid(),
        "executable": sys.executable,
        "root": str(root.resolve()),
        "persona": persona,
        "explicit_directory": os.environ.get("DCBOTS_SECRETS_DIR"),
        "environment_token_nonempty": environment_present,
        "private_path": None,
        "selected_path": None,
        "private_raw_exists": False,
        "raw_exists": False,
        "stat_ok": False,
        "stat_error": None,
        "read_ok": False,
        "read_error": None,
        "bytes_read": None,
        "utf8_bom": None,
        "utf16": None,
        "file_token_key_present": False,
        "file_token_nonempty": False,
        "dotenv_syntax_errors": False,
        "file_status": "configuration_error",
        "effective_token_nonempty": False,
    }

    def error_info(exc):
        # str(exc) could contain invalid file bytes. Only fixed class/codes.
        return {"type": type(exc).__name__, "errno": getattr(exc, "errno", None),
                "winerror": getattr(exc, "winerror", None)}

    try:
        private = private_env_path(persona)
        selected = credentials_file(root, persona)
    except (ValueError, OSError) as exc:
        report["path_error"] = error_info(exc)
        return report
    report.update(private_path=str(private), selected_path=str(selected),
                  private_raw_exists=os.path.exists(private), raw_exists=os.path.exists(selected),
                  selected_source="private_file" if selected == private else "project_file")
    try:
        info = os.stat(selected)
        report.update(stat_ok=True, stat_bytes=info.st_size, stat_mtime_ns=info.st_mtime_ns,
                      stat_regular_file=stat.S_ISREG(info.st_mode))
    except OSError as exc:
        report["stat_error"] = error_info(exc)
    # Do not use a different path if stat fails: the discrepancy itself matters.
    try:
        raw = selected.read_bytes()
    except OSError as exc:
        report["read_error"] = error_info(exc)
        report["file_status"] = "file_missing" if isinstance(exc, FileNotFoundError) else "read_error"
        report["effective_token_nonempty"] = environment_present and isinstance(exc, FileNotFoundError)
        return report
    report.update(read_ok=True, bytes_read=len(raw), utf8_bom=raw.startswith(b"\xef\xbb\xbf"),
                  utf16=raw.startswith((b"\xff\xfe", b"\xfe\xff")))
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        report["read_error"] = error_info(exc)
        report["file_status"] = "encoding_error"
        return report
    # Bindings allow detecting parser failures without its warning logger and
    # without putting any unrecognized key or value in the result.
    bindings = list(parse_stream(StringIO(decoded)))
    report["dotenv_syntax_errors"] = any(binding.error for binding in bindings)
    # Match dotenv_values interpolation even if an unrelated line is malformed,
    # while bypassing the parser's warning logger. No process environment writes.
    values = dict(resolve_variables(
        ((binding.key, binding.value) for binding in bindings if binding.key is not None),
        override=True,
    ))
    key_present = "DISCORD_TOKEN" in values
    nonempty = bool((values.get("DISCORD_TOKEN") or "").strip())
    report.update(file_token_key_present=key_present, file_token_nonempty=nonempty,
                  effective_token_nonempty=environment_present or nonempty)
    if nonempty:
        report["file_status"] = "token_present"
    elif not raw:
        report["file_status"] = "file_empty"
    elif report["dotenv_syntax_errors"]:
        report["file_status"] = "malformed_file"
    else:
        report["file_status"] = "token_empty" if key_present else "token_key_missing"
    return report
