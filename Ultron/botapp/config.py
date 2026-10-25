from __future__ import annotations

import copy
import json
import re
from string import Formatter
from datetime import time
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


def merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key != "level_roles" and isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def public_url(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or any(c.isspace() or c in "<>" for c in value) or len(value) > 1000):
        raise ValueError("Bitte eine vollständige HTTPS-Adresse ohne Leerzeichen verwenden.")
    return value


def validate_source(platform: str, account: str) -> str:
    pattern = r"UC[A-Za-z0-9_-]{22}" if platform == "youtube" else (r"[A-Za-z0-9_.]{1,24}" if platform == "tiktok" else r"[A-Za-z0-9_]{1,25}")
    if platform not in {"youtube", "twitch", "tiktok"} or not re.fullmatch(pattern, account):
        raise ValueError("YouTube braucht die UC-Kanal-ID (24 Zeichen), Twitch/TikTok den Kanalnamen ohne @.")
    return account.lower() if platform != "youtube" else account


class Config:
    def __init__(self, root: Path):
        self.root = root
        self.base = json.loads((root / "config.json").read_text(encoding="utf-8-sig"))
        local = root / "config.local.json"
        if local.exists():
            self.base = merge(self.base, json.loads(local.read_text(encoding="utf-8-sig")))
        self.validate(self.base)
        for guild in self.base.get("guilds", {}).values():
            self.validate(merge(self.base, guild))

    @staticmethod
    def validate(c: dict) -> None:
        from .settings_schema import validate_extensions
        validate_extensions(c)
        if "embed_templates" in c:
            from .presentation import validate_templates
            validate_templates(c["embed_templates"])
        if c["persona"] not in {"jarvis", "ultron"}:
            raise ValueError("persona muss jarvis oder ultron sein.")
        if not isinstance(c["prefixes"], list) or not c["prefixes"] or any(not isinstance(p, str) or not p.strip() for p in c["prefixes"]):
            raise ValueError("Mindestens ein nicht leeres Präfix wird benötigt.")
        ignored = c.get("ignored_prefixes", [])
        if not isinstance(ignored, list) or any(not isinstance(p, str) or not p.strip() for p in ignored):
            raise ValueError("ignored_prefixes muss eine Liste nicht leerer Präfixe sein.")
        if {p.casefold() for p in ignored} & {p.casefold() for p in c["prefixes"]}:
            raise ValueError("Ein Präfix darf nicht gleichzeitig aktiviert und ignoriert sein.")
        try:
            ZoneInfo(c["timezone"])
        except (KeyError, ValueError):
            raise ValueError("Unbekannte Zeitzone. Bitte zum Beispiel Europe/Vienna verwenden.") from None
        try:
            birthday_time = time.fromisoformat(c["birthday_time"])
        except ValueError:
            raise ValueError("Geburtstags-Uhrzeit als HH:MM eingeben, zum Beispiel 00:00 oder 09:30.") from None
        if birthday_time.tzinfo is not None:
            raise ValueError("birthday_time darf keine eigene Zeitzone enthalten.")
        if c["leap_day"] not in {"feb28", "mar1", "only_leap_years"}:
            raise ValueError("Ungültige leap_day-Regel.")
        for field in ("text_xp", "text_cooldown_seconds", "minimum_message_length", "voice_xp_per_minute"):
            if not isinstance(c[field], int) or c[field] < 0:
                raise ValueError(f"{field} muss eine nicht negative Ganzzahl sein.")
        if c.get("command_mode", "prefix") not in {"slash", "prefix"}:
            raise ValueError("command_mode muss slash oder prefix sein.")
        for key in ("voice_message_xp_per_minute", "voice_minimum_members"):
            if not isinstance(c.get(key, 0), int) or c.get(key, 0) < 0:
                raise ValueError(f"{key} muss eine nicht negative Ganzzahl sein.")
        if not isinstance(c["poll_seconds"], int) or c["poll_seconds"] < 30:
            raise ValueError("poll_seconds muss mindestens 30 sein.")
        if not re.fullmatch(r"#[a-fA-F0-9]{6}", c["color"]):
            raise ValueError("color muss eine Hex-Farbe wie #38bdf8 sein.")
        for value in c["links"].values():
            if value:
                public_url(value)
        for value in c["channels"].values():
            if value is not None and (not str(value).isdigit() or int(value) <= 0):
                raise ValueError("Kanal-IDs müssen positive Zahlen oder null sein.")
        for level, role in c["level_roles"].items():
            if not str(level).isdigit() or not str(role).isdigit() or int(role) <= 0:
                raise ValueError("Levelrollen: Level auf positive Rollen-ID abbilden.")
        for source in c["sources"]:
            validate_source(source["platform"], source["account"])
            if source.get("livestreams", False) and source["platform"] != "youtube":
                raise ValueError("livestreams ist nur bei YouTube-Quellen zusätzlich erforderlich.")
        for key in ("admin_role_ids", "moderator_role_ids", "protected_role_ids"):
            if not isinstance(c.get(key, []), list) or any(not str(r).isdigit() or int(r) <= 0 for r in c.get(key, [])):
                raise ValueError(f"{key} muss eine Liste positiver Rollen-IDs sein.")
        if not isinstance(c.get("messages", {}), dict) or not isinstance(c.get("command_aliases", {}), dict):
            raise ValueError("messages und command_aliases müssen Objekte mit benannten Einträgen sein.")
        for template in c.get("messages", {}).values():
            if not isinstance(template, str) or len(template) > 1500:
                raise ValueError("Nachrichtenvorlagen dürfen höchstens 1500 Zeichen enthalten.")
            for _, field, spec, conversion in Formatter().parse(template):
                if field is not None and (field not in {"name", "user_id", "server", "member_count"} or spec or conversion):
                    raise ValueError("Vorlagen erlauben nur {name}, {user_id}, {server} und {member_count} ohne Formatoptionen.")
        canonical = {"youtube", "twitch", "tiktok", "instagram", "twitter", "facebook", "discord", "playstation", "xbox", "nintendo", "linktree", "help", "birthday", "congratulate", "rank", "setup", "link", "quelle", "rollen", "ping", "ban", "unban", "timeout", "kick", "untimeout", "reinvite"}
        for alias, command in c.get("command_aliases", {}).items():
            if not re.fullmatch(r"[\w-]{1,32}", alias) or command not in canonical:
                raise ValueError("command_aliases braucht kurze Befehlsnamen mit gültigem internen Ziel.")
        if not isinstance(c.get("live_poll_seconds", 1800), int) or c.get("live_poll_seconds", 1800) < 300:
            raise ValueError("live_poll_seconds muss mindestens 300 sein.")
        allowed = {"links", "birthdays", "rank", "activity", "notifications", "join_log", "leave_log", "message_logs", "server_logs", "ban", "unban", "timeout", "kick", "untimeout", "reinvite"}
        if not isinstance(c["features"], list) or set(c["features"]) - allowed:
            raise ValueError("Unbekannte Funktion in features.")

    def guild(self, guild_id: int, overrides: dict | None = None) -> dict:
        return merge(merge(self.base, self.base.get("guilds", {}).get(str(guild_id), {})), overrides or {})
