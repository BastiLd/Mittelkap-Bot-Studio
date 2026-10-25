"""Safe local diagnostics: no network, no bot process and no credential values."""
from __future__ import annotations

import json
from pathlib import Path

from botapp.secrets import credential_diagnostics

ROOT = Path(__file__).resolve().parent
REASONS = {
    "configuration_error": "Token-Pfad konnte nicht bestimmt werden.",
    "file_missing": "Token-Datei fehlt auf diesem Rechner.",
    "read_error": "Token-Datei kann nicht gelesen werden.",
    "encoding_error": "Dateikodierung nicht lesbar. Bitte als UTF-8 speichern.",
    "file_empty": "Token-Datei ist vollständig leer.",
    "token_key_missing": "Datei lesbar, aber die Zeile DISCORD_TOKEN= fehlt.",
    "token_empty": "DISCORD_TOKEN ist vorhanden, aber ohne Wert.",
    "malformed_file": "Dateiformat ungültig; kein lesbarer DISCORD_TOKEN gefunden.",
    "token_present": "Datei lesbar, DISCORD_TOKEN ist eingetragen.",
}


def main():
    persona = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["persona"]
    report = credential_diagnostics(ROOT, persona)
    folder = ROOT / "logs"
    folder.mkdir(exist_ok=True)
    output = folder / "start-diagnose.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{persona.title()} auf {report['hostname']} als {report['username']}")
    print(f"Token-Datei: {report['selected_path'] or '(nicht bestimmbar)'}")
    print(REASONS[report["file_status"]])
    if report["environment_token_nonempty"]:
        print("Ein Token aus der Prozessumgebung hat Vorrang.")
    print(f"Diagnose ohne Tokenwerte: {output}")
    return 0 if report["effective_token_nonempty"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
