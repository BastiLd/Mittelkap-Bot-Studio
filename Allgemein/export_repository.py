"""Repeatable public-source export. Uses the package allowlist; never reads secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from build_packages import FONT_FILES, packlists

ROOT = Path(__file__).resolve().parent.parent
AREAS = {"Jarvis", "Ultron", "Webseite", "Allgemein"}
ROOT_FILES = {"README.md", ".gitignore", ".gitattributes", "start.py", "requirements.txt"}
MANIFEST = "Allgemein/export-manifest.json"
REPORT = "Allgemein/export-scan.json"
TEXT_TYPES = {".py", ".js", ".json", ".html", ".css", ".svg", ".md", ".txt", ".example"}
TEXT_NAMES = {".gitignore", ".gitattributes"}
# This is the existing, explicitly requested protection identity, not a credential.
PROTECTED_ID = "965593518745731152"
TOKEN_PATTERNS = {
    "discord_token": re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{23,30}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,120}(?![A-Za-z0-9_-])"),
    "github_token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{70,})"),
    "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "webhook_secret": re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]{35,}"),
    "literal_credential": re.compile(r'''(?i)(?:DISCORD_TOKEN|CLIENT_SECRET|ACCESS_TOKEN|API_KEY|DASHBOARD_SETUP_KEY)\s*[=:]\s*["']?[A-Za-z0-9_-]{25,}'''),
    "private_network_address": re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"),
    "private_windows_path": re.compile(r"(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s]+"),
}

PUBLIC_README = """# Mittelkap · Jarvis, Ultron und Bot-Studio

Zwei Discord-Bots mit deutscher Bedienung und einer selbst gehosteten Verwaltungswebsite. Dieses öffentliche Repository enthält **Quellcode und bereinigte Beispiele**. Tokens, Webkonten, Passwörter, Serverdaten, Protokolle und persönliche Konfigurationen sind nicht enthalten.

## Vier Bereiche

| Ordner | Aufgabe |
| --- | --- |
| [Jarvis](Jarvis) | Begrüßung, Profillinks, Geburtstage, Aktivität/Rangkarte, Inhaltsmeldungen und positive Moderationsaktionen |
| [Ultron](Ultron) | Abschiede, Banns, Kicks und zeitweises Stummschalten |
| [Webseite](Webseite) | Python-Backend und Oberfläche: Konten/Rechte, Einstellungen, Protokolle, Mitglieder und Embed-Editor |
| [Allgemein](Allgemein) | Gemeinsame Anleitung, Environment-Beispiel, Paket-/Exportwerkzeuge und Font-/Prüfhinweise |

## Installation und Start

Python **3.12 oder 3.13** verwenden und `python -m pip install -r requirements.txt` ausführen. Die privaten Environment-Werte stehen beschrieben in [Allgemein/Manager.env.example](Allgemein/Manager.env.example); echte Werte im Prozessmanager oder einer privaten Umgebung hinterlegen. Die Beispieldatei wird nicht automatisch geladen.

Für zwei getrennte Prozessmanager-Profile jeweils dieses Repository vollständig auschecken:

| Profil | Startbefehl | Startet |
| --- | --- | --- |
| Jarvis | `python start.py --services jarvis` | Jarvis und das Website-Backend |
| Ultron | `python start.py --services ultron` | ausschließlich Ultron |

Beide Profile müssen denselben **absoluten** Pfad `DCBOTS_DASHBOARD_DIR` verwenden. Dort liegen die gemeinsamen Konten und Steuerungsaufträge. Als Einstieg pro Bot funktionieren auch `python Jarvis/main.py` und `python Ultron/main.py`; sie reichen an die Startsteuerung im Repository-Stamm weiter. Vor dem Start prüft `python start.py --services jarvis --check` beziehungsweise `--services ultron --check` ausschließlich Dateien, Variablen und Bibliotheken, ohne Discord-Verbindung.

Alternativ startet `python start.py --services all` alle drei Dienste in einem Profil. Die Alternativen nicht gleichzeitig mit denselben Tokens betreiben. Der Supervisor leitet Stoppsignale weiter und beendet die zu seinem Profil gehörenden Prozesse. Der tatsächliche Discord-Online-Status wird separat durch die Bots gemeldet.

## Einrichtung

Die mitgelieferten Bot-Konfigurationen haben leere Links, Quellen, Rollen und Kanalziele. Diese nach dem Start über `/einstellungen` beziehungsweise die Website einrichten. Discord benötigt die Intents **Server Members** und **Message Content** sowie die jeweils erforderlichen Kanal-/Moderationsrechte.

`DASHBOARD_PUBLIC_URL` muss exakt zur Browseradresse passen. Weitere gezielt erlaubte Basisadressen können durch Komma getrennt in `DASHBOARD_ADDITIONAL_URLS` stehen; Host und Origin werden daraus freigegeben. HTTPS-Anmeldungen erhalten Secure-Cookies, vorhandene LAN-Adressen bleiben nutzbar. Das Backend hört standardmäßig auf Port 8765; ein Reverse-Proxy erhält Host/Origin und leitet `/api/` unverändert weiter. Für öffentlichen Zugriff HTTPS verwenden. Beim ersten Einrichten wird ein eigener zufälliger `DASHBOARD_SETUP_KEY` benötigt; anschließend im Browser das Passwort für das Inhaberkonto **basti** festlegen. Teammitglieder bekommen getrennte Konten und Rechte.

**Projektbindung:** Die bestehende Schutzregel für Bastis Discord-ID `965593518745731152` ist bewusst erhalten. Die ID ist kein Token. Dieses Projekt ist auf diesen Inhaber zugeschnitten; für einen unabhängigen Fork müssen Identitäts-/Schutzregeln bewusst geprüft werden. Der Bot kann Discords Rollenreihenfolge nicht umgehen.

## Gestaltung und Daten

38 Kategorien mit Beispielen, 24 lokale Designs in sieben Layouts und ein PNG-Renderer für echte Schriften, Farben und Schatten. Auswahl und Vorschau speichern oder senden nichts automatisch. Funktionen und Grenzen beschreibt [Allgemein/STUDIO_V4.md](Allgemein/STUDIO_V4.md).

Laufzeitdaten liegen in den jeweiligen Bot-Datenordnern und dem privaten gemeinsamen Control-Verzeichnis. Sie gehören nicht in Git. Bestehende Datenbanken vor einem Umzug konsistent sichern und getrennt übertragen; nie mit diesem bereinigten Quellcode-Export überschreiben.

Die enthaltenen freien Schriften Archivo, Roboto und Roboto Mono enthalten ihre Original-OFL-Lizenzen und Herkunftsnachweise unter `Jarvis/assets/fonts` und `Ultron/assets/fonts`. Es werden keine Microsoft-Schriften oder Filmreferenzbilder verteilt. Die früheren Figuren-GIFs sind nicht Bestandteil dieses Exports.

Die öffentliche Exportprüfung steht in [Allgemein/export-scan.json](Allgemein/export-scan.json). Sie dokumentiert die ausgeführten statischen Prüfungen und ist keine Zusicherung, dass beliebige spätere Dateien geheimnisfrei sind. Änderungen erneut prüfen, bevor sie veröffentlicht werden. Eine laufende Bereitstellung wird durch dieses Repository nicht behauptet.
"""

GENERAL_README = """# Allgemein

Dieser Bereich enthält gemeinsame Start-/Paketwerkzeuge und öffentliche Anleitung. Maßgeblich für den Start ist [../start.py](../start.py), die gemeinsame Abhängigkeitsliste steht unter [../requirements.txt](../requirements.txt).

- `Manager.env.example`: ausschließlich leere Zugangsdaten und generische Beispieladressen. Nicht als echte Konfiguration veröffentlichen.
- `STUDIO_V4.md`: Funktions- und Bedienübersicht ohne private Bereitstellungsdaten.
- `build_packages.py`: explizite Paket-Packliste; `python Allgemein/build_packages.py --output-dir <privater-ausgabeordner>` erzeugt Codepakete.
- `export_repository.py`: erzeugt aus dem Quellprojekt einen neuen bereinigten Unterordner `Repository`; vorhandene unbekannte Dateien führen zum Abbruch. Quellkonfigurationen werden nicht verändert. Der Export liest keine privaten Dateien und führt keine Veröffentlichung aus.
- `export-manifest.json`: Dateipfade und SHA-256-Prüfsummen des Quellcode-Exports. UTF-8-Text wird vor der Berechnung auf LF-Zeilenenden normalisiert; `.gitattributes` erhält diese Form auch beim Git-Checkout. Binärdateien bleiben unverändert.
- `export-scan.json`: Prüfbericht ohne gefundene Geheimniswerte; die bewusst erhaltene Schutz-ID wird nur über ihre Fundstellen dokumentiert.

Die gebündelten Schriften liegen in beiden Botordnern mit ihren vollständigen SIL-OFL-Lizenzen und Quellenangaben. Die Website benutzt das gleiche Kartenmodul wie Jarvis. Kein Test, Start oder Export löst automatisch eine Moderation oder Privatnachricht aus.
"""

ENV_EXAMPLE = """# Werte privat im Prozessmanager setzen. Diese Beispieldatei wird nicht geladen.
JARVIS_DISCORD_TOKEN=
ULTRON_DISCORD_TOKEN=
# Exakte Browseradresse; hinter einem öffentlichen Proxy zum Beispiel https://bots.example.com
DASHBOARD_PUBLIC_URL=http://localhost:8765
# Optional: weitere exakte Basisadressen, durch Komma getrennt
DASHBOARD_ADDITIONAL_URLS=
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8765
# Für BEIDE Profile derselbe absolute private Pfad. Beispiel für Linux:
DCBOTS_DASHBOARD_DIR=/srv/mittelkap-private/control
# Zufälligen geheimen Einrichtungsschlüssel selbst festlegen; nur bei neuer Installation.
DASHBOARD_SETUP_KEY=
JARVIS_YOUTUBE_API_KEY=
JARVIS_TWITCH_CLIENT_ID=
JARVIS_TWITCH_CLIENT_SECRET=
JARVIS_TIKTOK_ACCESS_TOKEN=
JARVIS_TIKTOK_REFRESH_TOKEN=
JARVIS_TIKTOK_CLIENT_KEY=
JARVIS_TIKTOK_CLIENT_SECRET=
"""

GITIGNORE = """# Private configuration and runtime data must stay outside version control.
**/.env
**/.env.*
!**/*.env.example
**/config.local.json
**/config.json.local
**/data/
**/logs/
**/*.log
**/*.db
**/*.sqlite*
**/*.db-wal
**/*.db-shm
**/*.pid
**/.venv/
**/venv/
**/__pycache__/
**/.pytest_cache/
**/*.pyc
private*/
**/private*/
secrets/
**/secrets/
Privat/
Server.env
Manager.env
.qa/
dist/
**/dist/
Repository/
**/*.zip
.DS_Store
Thumbs.db
"""

GIT_ATTRIBUTES = """# The export manifest hashes canonical UTF-8/LF text and unchanged binaries.
* text=auto
*.py text eol=lf
*.md text eol=lf
*.json text eol=lf
*.js text eol=lf
*.css text eol=lf
*.html text eol=lf
*.svg text eol=lf
*.txt text eol=lf
*.env.example text eol=lf
.gitignore text eol=lf
.gitattributes text eol=lf
*.png -text
*.jpg -text
*.jpeg -text
*.webp -text
*.gif -text
*.ico -text
*.ttf -text
*.otf -text
*.woff -text
*.woff2 -text
"""


def is_text_file(name):
    path = Path(name)
    return path.suffix.lower() in TEXT_TYPES or path.name in TEXT_NAMES


def normalize_file(name, content):
    """Hash exactly the bytes Git will keep: BOM-free UTF-8/LF, binaries untouched."""
    if not is_text_file(name):
        return content
    return content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sanitized_config(path):
    source = json.loads(path.read_text(encoding="utf-8"))
    # Only established noncredential configuration keys may cross this boundary.
    safe = {"name", "persona", "prefixes", "ignored_prefixes", "color", "features", "timezone", "birthday_time",
            "leap_day", "poll_seconds", "text_xp", "text_cooldown_seconds", "minimum_message_length",
            "voice_xp_per_minute", "voice_enabled", "admin_role_ids", "moderator_role_ids", "protected_role_ids",
            "level_roles", "links", "channels", "log_message_content", "sources", "guilds", "live_poll_seconds",
            "command_aliases", "messages", "command_mode", "prefix_commands_enabled", "voice_message_xp_per_minute",
            "voice_minimum_members", "creator_name", "history_scan_limit", "history_scan_overrides", "stream_delay_seconds",
            "command_settings", "embed_templates"}
    config = {key: value for key, value in source.items() if key in safe}
    config["name"], config["persona"] = path.parent.name, path.parent.name.lower()
    config.update(channels={key: None for key in config.get("channels", {})},
                  links={key: "" for key in config.get("links", {})}, sources=[], guilds={},
                  admin_role_ids=[], moderator_role_ids=[], protected_role_ids=[], level_roles={},
                  history_scan_overrides={}, command_settings={}, command_aliases={}, creator_name="Mittelkap")
    # User-authored overrides can contain member references, private URLs or channel IDs.
    config["embed_templates"] = {}
    config["messages"] = {
        "welcome": "Willkommen {name} auf {server}! Mit /hilfe findest du die Möglichkeiten.",
        "farewell": "{name} hat den Server verlassen. Alles Gute!",
        "birthday": "Alles Gute zum Geburtstag, {name}!",
    }
    return json_bytes(config)


def sanitized_catalog(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    # Samples are illustrative; retain no creator handles from the local deployment.
    text = json.dumps(data, ensure_ascii=False)
    for handle in ("KingisdaYT", "kingisdayt", "kingisda", "mittelkap7"):
        text = text.replace(handle, "beispielcreator")
    return json_bytes(json.loads(text))


def public_v4(root):
    path = root / "STUDIO_V4.md"
    if not path.is_file():
        path = root / "Allgemein/STUDIO_V4.md"
    text = path.read_text(encoding="utf-8")
    start = text.find("## Zusammenarbeit")
    end = text.find("## Tatsächlich geprüfter Umfang")
    if start < 0:
        raise ValueError("Öffentliche Funktionsdokumentation konnte nicht abgegrenzt werden.")
    body = text[start:end if end >= 0 else None]
    return ("# Bot-Studio V4 · Funktionen und Bedienung\n\nÖffentliche Funktionsübersicht. Installation: [Repository-Anleitung](../README.md). Lokale Bereitstellungsdaten und Prüfprotokolle sind nicht Teil dieses Dokuments.\n\n" + body).encode("utf-8")


def public_plan(root=ROOT):
    root = Path(root).resolve()
    plan = {}
    entries = packlists(root)["Mittelkap-Manager.zip"]
    for name, path in entries.items():
        parts = Path(name).parts
        if parts[0] in {"Jarvis", "Ultron"}:
            if len(parts) > 2 and parts[1] == "assets":
                allowed = ((parts[2] in {"banners", "card-previews"} and path.suffix.lower() == ".png") or
                           (parts[2] == "fonts" and parts[-1] in FONT_FILES))
                if not allowed:
                    continue
            target = name
        elif name.startswith("Dashboard/"):
            target = "Webseite/" + name[len("Dashboard/"):]
        elif name in {"start.py", "requirements.txt"}:
            target = name
        else:
            continue  # Never export deployment history, private addresses or raw env examples.
        if not path.is_file() or path.is_symlink():
            raise ValueError("Erforderliche öffentliche Datei fehlt oder ist verlinkt: " + target)
        if name.endswith("/config.json"):
            plan[target] = sanitized_config(path)
        elif name.endswith("/editor_catalog.json"):
            plan[target] = sanitized_catalog(path)
        else:
            plan[target] = path.read_bytes()
    # WebHafen must expose only the static site, never Python or private files.
    for name, content in list(plan.items()):
        if name.startswith("Webseite/static/"):
            plan["Webseite/public/" + name[len("Webseite/"):]] = content
    plan["Webseite/public/index.html"] = plan["Webseite/static/index.html"]
    deploy = root / ("deployment" if (root / "deployment").is_dir() else "Allgemein")
    for leaf in ("start.py", "requirements.txt", "build_packages.py", "export_repository.py"):
        path = deploy / leaf
        if not path.is_file() or path.is_symlink():
            raise ValueError("Exportwerkzeug fehlt oder ist verlinkt: " + leaf)
        plan["Allgemein/" + leaf] = path.read_bytes()
    plan.update({"README.md": PUBLIC_README.encode(), ".gitignore": GITIGNORE.encode(), ".gitattributes": GIT_ATTRIBUTES.encode(),
                 "Allgemein/README.md": GENERAL_README.encode(),
                 "Allgemein/Manager.env.example": ENV_EXAMPLE.encode(),
                 "Allgemein/STUDIO_V4.md": public_v4(root)})
    for bot in ("Jarvis", "Ultron"):
        mode = bot.lower()
        plan[f"{bot}/main.py"] = (f'''"""Start {bot} through the root supervisor; preserve manager stop signals."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
os.execv(sys.executable, [sys.executable, str(root / "start.py"), "--services", "{mode}", *sys.argv[1:]])
''').encode()
        plan[f"{bot}/README.md"] = (f"# {bot}\n\nStart im Repository-Stamm: `python start.py --services {mode}`. Alternativ `python {bot}/main.py`. {'Dieses Profil startet zusätzlich das Website-Backend.' if bot == 'Jarvis' else 'Dieses Profil startet nur Ultron; DCBOTS_DASHBOARD_DIR muss auf das gemeinsame private Control-Verzeichnis des Jarvis-Profils zeigen.'}\n\nInstallation, benötigte Environment-Werte und Schutzregeln: [Repository-Anleitung](../README.md). Die mitgelieferte config.json enthält keine persönlichen Kanal-, Rollen- oder Profildaten.\n").encode()
    plan["Webseite/README.md"] = "# Webseite\n\n`server.py` stellt das private API-Backend und die Oberfläche unter `static/` bereit. Der reguläre Start erfolgt zusammen mit Jarvis über `python start.py --services jarvis` im Repository-Stamm. Beide Bot-Profile teilen das private Control-Verzeichnis.\n\nDie Oberfläche kann alternativ statisch gehostet werden, wenn derselbe Ursprung `/api/` an dieses Backend weiterleitet. `DASHBOARD_PUBLIC_URL`, Host/Origin und HTTPS entsprechend der [Repository-Anleitung](../README.md) konfigurieren. API-Schlüssel oder Bot-Tokens gehören niemals in JavaScript oder statische Dateien.\n".encode()
    return plan


def scan(plan):
    findings, owner_locations, snowflakes = [], [], []
    blocked = []
    for name, content in sorted(plan.items()):
        parts = Path(name).parts
        if parts[0] not in AREAS and name not in ROOT_FILES:
            blocked.append(name)
        if any(part.lower() in {"data", "logs", "private", "privat", "secrets", "references", "__pycache__", ".venv", "tests"} for part in parts):
            blocked.append(name)
        leaf = Path(name).name.lower()
        if Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log", ".zip", ".env"} or leaf in {".env", "config.local.json"} or (leaf.startswith(".env.") and not leaf.endswith(".example")):
            blocked.append(name)
        if not is_text_file(name):
            continue
        text = content.decode("utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for label, expression in TOKEN_PATTERNS.items():
                if expression.search(line):
                    findings.append({"path": name, "line": number, "check": label})
            if PROTECTED_ID in line:
                owner_locations.append({"path": name, "line": number})
            # Snowflake-shaped constants are reviewed separately; never print their values.
            for value in re.findall(r"(?<![A-Za-z0-9])\d{17,20}(?![A-Za-z0-9])", line):
                if value not in {PROTECTED_ID, "123456789012345678", "100000000000000000", "1000000000000000000", "18446744073709551615"}:
                    snowflakes.append({"path": name, "line": number})
    return {"format": 1, "files_checked": len(plan), "private_files_read": False,
            "scope": "Allowlist; bereinigte Konfiguration; Pfad- und Textmusterprüfung. Kein Vergleich mit privaten Zugangsdaten.",
            "blocked_paths": sorted(set(blocked)), "potential_secrets": findings,
            "other_snowflake_locations": snowflakes, "preserved_owner_id_locations": owner_locations}


def export(output=None, root=ROOT):
    root = Path(root).resolve()
    output = Path(output or root / "Repository")
    if output.is_symlink():
        raise ValueError("Exportziel darf kein Symlink sein.")
    output = output.resolve()
    # Only a direct child of this exact source workspace may be updated.
    if output.parent != root or output.name != "Repository":
        raise ValueError("Exportziel muss der direkte Unterordner Repository im Quellprojekt sein.")
    plan = {name: normalize_file(name, content) for name, content in public_plan(root).items()}
    report = scan(plan)
    if report["blocked_paths"] or report["potential_secrets"] or report["other_snowflake_locations"]:
        # Diagnostic content contains paths/check names/line numbers, never matching secrets.
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise ValueError("Öffentlicher Export hat Prüffunde; keine Dateien geschrieben.")
    plan[REPORT] = json_bytes(report)
    manifest = {"format": 1, "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(plan.items())}}
    plan[MANIFEST] = json_bytes(manifest)
    old_files = set()
    if output.exists():
        previous = output / MANIFEST
        if previous.is_file():
            old_files = set(json.loads(previous.read_text(encoding="utf-8"))["files"]) | {MANIFEST}
        actual = set()
        for path in output.rglob("*"):
            relative = path.relative_to(output).as_posix()
            if relative == ".git" or relative.startswith(".git/"):
                continue
            if path.is_symlink():
                raise ValueError("Verlinkte Datei im Exportziel: " + relative)
            if path.is_file():
                actual.add(relative)
        unknown = actual - old_files - set(plan)
        if unknown:
            raise ValueError("Unbekannte Exportdateien werden nicht verändert: " + ", ".join(sorted(unknown)))
        stale = actual - set(plan)
        if stale:
            raise ValueError("Veraltete Exportdateien bitte zunächst einzeln prüfen: " + ", ".join(sorted(stale)))
    for name, content in sorted(plan.items()):
        path = output / name
        if not path.resolve().is_relative_to(output):
            raise ValueError("Ungültiger Exportpfad: " + name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Öffentlichen, bereinigten Repository-Ordner erstellen; ohne Git oder Veröffentlichung.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "Repository")
    args = parser.parse_args()
    try:
        result = export(args.output_dir)
    except (ValueError, OSError) as error:
        print("Export abgebrochen: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    print(f"Repository erstellt: {result['files_checked']} Quelldateien geprüft; keine Geheimnismuster, privaten Pfade oder unbekannten Discord-IDs gefunden.")
    print("Schutz-ID unverändert erhalten; Fundstellen stehen ohne Geheimniswerte in Allgemein/export-scan.json.")
