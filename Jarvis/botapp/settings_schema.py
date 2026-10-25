"""One validated settings contract for Discord controls and the local dashboard."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

OWNER_ID = 965593518745731152
PERSONA_FEATURES = {
    "jarvis": {"links", "birthdays", "rank", "activity", "notifications", "join_log", "message_logs", "server_logs", "unban", "untimeout", "reinvite"},
    "ultron": {"leave_log", "ban", "timeout", "kick"},
}
CHANNEL_LABELS = {
    "welcome": "👋 Willkommen", "farewell": "🚪 Abschied", "birthdays": "🎂 Geburtstage",
    "videos": "▶️ YouTube-Videos", "youtube_streams": "🔴 YouTube-Livestreams",
    "tiktok": "🎬 TikTok-Videos", "twitch": "🟣 Twitch-Livestreams",
    "logs": "📋 Allgemeine Logs", "moderation": "🛡️ Moderationsprotokoll", "links": "🔗 Profillinks",
}
COMMAND_DEFAULTS = {
    "help": ("hilfe", "Befehle, Beispiele und erste Schritte verständlich erklärt"),
    "ping": ("status", "Erreichbarkeit und Aufgaben dieses Bots anzeigen"),
    "rank": ("rang", "Level, XP, Sprachzeit und Mitgliedsdauer als Rangkarte anzeigen"),
    "birthday": ("geburtstag", "Deinen Geburtstag eintragen, ändern oder löschen – ohne Geburtsjahr"),
    "congratulate": ("gratuliere", "Einem Mitglied einen öffentlichen Gruß im Geburtstagskanal senden"),
    "setup": ("einstellungen", "Verwaltung öffnen: Kanäle, Forum-Beiträge, Links, XP und Sichtbarkeit"),
    "link": ("profillink", "Ein öffentliches Profil verknüpfen; mit Adresse aus den Link entfernen"),
    "quelle": ("quelle", "YouTube-, Twitch- oder TikTok-Konto für automatische Meldungen einrichten"),
    "rollen": ("stufenrolle", "Eine Belohnungsrolle bei Erreichen einer bestimmten Stufe vergeben"),
    "timeout": ("stummschalten", "Ein Mitglied zeitweise stummschalten; Dauer zum Beispiel 10m oder 2h"),
    "ban": ("bannen", "Ein Mitglied vom Server sperren; die Maßnahme wird protokolliert"),
    "unban": ("entbannen", "Eine Serversperre aufheben; auf Wunsch eine private Einladung schicken"),
    "kick": ("kicken", "Ein Mitglied entfernen; es kann später über eine Einladung selbst zurückkehren"),
    "untimeout": ("stummschaltungaufheben", "Einen laufenden Timeout aufheben, damit das Mitglied wieder kommunizieren kann"),
    "reinvite": ("einladen", "Nach Kick oder Entbannung eine Einladung erstellen und auf Wunsch privat schicken"),
}
for _platform in ("youtube", "twitch", "tiktok", "instagram", "twitter", "facebook", "discord", "playstation", "xbox", "nintendo", "linktree"):
    COMMAND_DEFAULTS[_platform] = (_platform, f"Das hinterlegte {_platform.title()}-Profil öffnen")

PRIVATE_DEFAULTS = {"birthday", "setup", "link", "quelle", "rollen", "ban", "unban", "timeout", "kick", "untimeout", "reinvite", "congratulate"}
SCHEMA = {
    "birthday_time": {"label": "Uhrzeit der Geburtstagsgrüße", "type": "time", "help": "Täglich in der ausgewählten Zeitzone; ohne Geburtsjahr oder Altersangabe."},
    "timezone": {"label": "Zeitzone", "type": "text", "help": "Zum Beispiel Europe/Vienna; Sommerzeit wird automatisch berücksichtigt."},
    "text_xp": {"label": "XP pro Textnachricht", "type": "integer", "min": 0, "help": "0 schaltet Text-XP aus. Es gibt kein Minutenlimit."},
    "minimum_message_length": {"label": "Mindestlänge für Text-XP", "type": "integer", "min": 0, "help": "Anzahl Zeichen einer Nachricht, bevor XP vergeben werden."},
    "text_cooldown_seconds": {"label": "Pause zwischen Text-XP", "type": "integer", "min": 0, "help": "0 bedeutet keine Pause; ansonsten Sekunden pro Mitglied."},
    "voice_enabled": {"label": "Sprachchat-XP aktiv", "type": "boolean", "help": "Zählt Anwesenheit; der Bot hört nicht mit und nimmt nichts auf."},
    "voice_xp_per_minute": {"label": "XP pro Sprachchat-Minute", "type": "integer", "min": 0, "help": "Für anwesende, nicht stummgeschaltete Mitglieder."},
    "voice_message_xp_per_minute": {"label": "XP pro Sprachnachrichten-Minute", "type": "integer", "min": 0, "help": "Verwendet nur die Längenangabe von Discord; 0 schaltet diese XP aus."},
    "voice_minimum_members": {"label": "Mindestanzahl im Sprachkanal", "type": "integer", "min": 1, "help": "1 erlaubt XP auch allein im Sprachkanal."},
    "log_message_content": {"label": "Nachrichteninhalt protokollieren", "type": "boolean", "help": "Zeigt bei Bearbeitungen und Löschungen den verfügbaren Text im Log."},
    "history_scan_limit": {"label": "Nachrichten beim Start einlesen", "type": "scan", "default": 50, "help": "Pro Kategorie: 50, 100, eigene Zahl, alle oder keine. Gespeicherte Verweise bleiben erhalten."},
    "stream_delay_seconds": {"label": "Verzögerung für Livestream-Meldungen", "type": "integer", "min": 0, "default": 0, "help": "Sekunden ab Erkennung warten, damit Titel und Thumbnail fertiggestellt werden können."},
    "poll_seconds": {"label": "Prüfintervall für neue Inhalte", "type": "integer", "min": 30, "help": "Sekunden zwischen Abrufen; Plattform-Zugangsdaten können erforderlich sein."},
    "live_poll_seconds": {"label": "YouTube-Live-Prüfintervall", "type": "integer", "min": 300, "help": "Sekunden zwischen Live-Abfragen. Ein YouTube-API-Schlüssel wird benötigt."},
    "color": {"label": "Akzentfarbe", "type": "color", "help": "Farbe der Embeds, zum Beispiel #38bdf8."},
    "creator_name": {"label": "Name des Creators", "type": "text", "help": "Anzeigename für Profile und neue Inhalte."},
}


def scan_limit(value):
    if isinstance(value, str):
        if value.casefold().strip() in {"alle", "all"}:
            return "all"
        if value.casefold().strip() in {"keine", "none", "aus"}:
            return 0
        if value.isdigit():
            value = int(value)
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("Scan-Anzahl: 0/keine, eine Zahl bis 1000000 oder alle verwenden.")
    return value


def command_options(settings: dict, command: str) -> dict:
    name, description = COMMAND_DEFAULTS.get(command, (command, command))
    return {"name": name, "description": description, "ephemeral": command in PRIVATE_DEFAULTS,
            "allowed_channel_ids": [], "enabled": True, **settings.get("command_settings", {}).get(command, {})}


def validate_extensions(c: dict):
    for key, item in SCHEMA.items():
        if item["type"] == "integer" and key in c:
            if type(c[key]) is not int or not item.get("min", 0) <= c[key] <= 1_000_000:
                raise ValueError(f"{item['label']}: eine ganze Zahl zwischen {item.get('min', 0)} und 1000000 eingeben.")
        if item["type"] in {"text", "time", "color"} and key in c:
            if not isinstance(c[key], str) or not 1 <= len(c[key]) <= 100:
                raise ValueError(f"{item['label']}: Text mit 1–100 Zeichen eingeben.")
    if not isinstance(c.get("sources"), list) or len(c["sources"]) > 100:
        raise ValueError("Quellen müssen eine Liste mit höchstens 100 Einträgen sein.")
    for source in c["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("platform"), str) or not isinstance(source.get("account"), str):
            raise ValueError("Jede Quelle braucht eine Plattform und ein Konto als Text.")
    if not isinstance(c.get("links"), dict) or any(not isinstance(v, str) for v in c["links"].values()):
        raise ValueError("Profillinks müssen Text sein; ein leerer Text entfernt den Link.")
    for key in ("voice_enabled", "log_message_content"):
        if key in c and type(c[key]) is not bool:
            raise ValueError(f"{SCHEMA[key]['label']} muss an oder aus sein.")
    if "history_scan_limit" in c:
        scan_limit(c["history_scan_limit"])
    overrides = c.get("history_scan_overrides", {})
    if not isinstance(overrides, dict) or any(key not in CHANNEL_LABELS and key not in COMMAND_DEFAULTS for key in overrides):
        raise ValueError("Scan-Ausnahmen müssen einer bekannten Kategorie oder einem Befehl zugeordnet sein.")
    for value in overrides.values():
        scan_limit(value)
    delay = c.get("stream_delay_seconds", 0)
    if type(delay) is not int or not 0 <= delay <= 86400:
        raise ValueError("Stream-Verzögerung muss zwischen 0 und 86400 Sekunden liegen.")
    commands = c.get("command_settings", {})
    if not isinstance(commands, dict):
        raise ValueError("Befehlseinstellungen müssen ein Objekt sein.")
    names = {}
    for key in COMMAND_DEFAULTS:
        item = commands.get(key, {})
        if not isinstance(item, dict) or set(item) - {"name", "description", "ephemeral", "allowed_channel_ids", "enabled"}:
            raise ValueError("Unbekannte Befehlseinstellung.")
        current = command_options(c, key)
        if not isinstance(current["name"], str) or not re.fullmatch(r"[a-zäöüß0-9_-]{1,32}", current["name"]):
            raise ValueError("Befehlsnamen: 1–32 Kleinbuchstaben, Ziffern, _ oder -.")
        if current["name"] in names:
            raise ValueError(f"Der Befehlsname /{current['name']} ist doppelt vergeben.")
        names[current["name"]] = key
        if not isinstance(current["description"], str) or not 1 <= len(current["description"]) <= 100:
            raise ValueError("Befehlsbeschreibungen müssen 1–100 Zeichen enthalten.")
        if type(current["ephemeral"]) is not bool or type(current["enabled"]) is not bool:
            raise ValueError("Sichtbarkeit und Aktivierung brauchen wahr/falsch.")
        ids = current["allowed_channel_ids"]
        if not isinstance(ids, list) or any(not str(v).isdigit() or int(v) <= 0 for v in ids):
            raise ValueError("Erlaubte Kanäle: positive Kanal-IDs oder eine leere Liste für alle Kanäle.")
        if key == "setup" and not current["enabled"]:
            raise ValueError("Die Verwaltung kann nicht deaktiviert werden.")
    if set(commands) - set(COMMAND_DEFAULTS):
        raise ValueError("Unbekannter Befehl in command_settings.")
    for source in c.get("sources", []):
        if "delay_seconds" in source and (type(source["delay_seconds"]) is not int or not 0 <= source["delay_seconds"] <= 86400):
            raise ValueError("Quellen-Verzögerung: 0–86400 Sekunden.")
        if source.get("channel_id") is not None and (not str(source["channel_id"]).isdigit() or int(source["channel_id"]) <= 0):
            raise ValueError("Das Quellen-Ziel muss eine gültige Kanal- oder Beitrag-ID sein.")
        if "enabled" in source and type(source["enabled"]) is not bool:
            raise ValueError("Quelle aktiviert muss wahr oder falsch sein.")
    if not isinstance(c.get("creator_name", "Mittelkap"), str) or len(c.get("creator_name", "")) > 100:
        raise ValueError("Der Creator-Name darf höchstens 100 Zeichen lang sein.")


def apply_settings(service, guild_id: int, patch: dict) -> dict:
    """Validate complete merged config before atomically replacing its stored overrides."""
    from .config import merge
    allowed = set(SCHEMA) | {"channels", "links", "sources", "messages", "embed_templates", "command_settings",
                             "history_scan_overrides", "level_roles", "features", "leap_day", "protected_role_ids",
                             "admin_role_ids", "moderator_role_ids"}
    if not isinstance(patch, dict) or set(patch) - allowed:
        raise ValueError("Diese Einstellung kann hier nicht geändert werden.")
    if "channels" in patch and (not isinstance(patch["channels"], dict) or set(patch["channels"]) - set(CHANNEL_LABELS) - {"streams"}):
        raise ValueError("Unbekannte Zielkanal-Kategorie.")
    if "links" in patch and (not isinstance(patch["links"], dict) or set(patch["links"]) - set(service.config.base["links"])):
        raise ValueError("Unbekannte Profil-Plattform.")
    if "features" in patch:
        features = patch["features"]
        if not isinstance(features, list) or any(not isinstance(v, str) for v in features):
            raise ValueError("Aktive Aufgaben müssen als Liste von Funktionsnamen angegeben werden.")
        if set(features) - PERSONA_FEATURES[service.config.base["persona"]]:
            raise ValueError("Diese Aufgabe gehört zum anderen Bot. Jarvis verwaltet Aktivität und Rang; Ultron Abschied, Bann und Stummschaltung.")
    patch = dict(patch)
    if "history_scan_limit" in patch:
        patch["history_scan_limit"] = scan_limit(patch["history_scan_limit"])
    if "history_scan_overrides" in patch:
        if not isinstance(patch["history_scan_overrides"], dict):
            raise ValueError("Scan-Ausnahmen brauchen Kategorie und zugehörige Anzahl.")
        patch["history_scan_overrides"] = {k: scan_limit(v) for k, v in patch["history_scan_overrides"].items()}
    stored = merge(service.store.settings(guild_id), patch)
    effective = service.config.guild(guild_id, stored)
    service.config.validate(effective)
    service.store.save_settings(guild_id, stored)
    return effective

