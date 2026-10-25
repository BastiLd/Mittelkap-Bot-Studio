"""Shared Discord embed styling and safe, editable message templates."""
from __future__ import annotations

import re
import json
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from string import Formatter
from urllib.parse import urlsplit

import discord

TEMPLATE_LABELS = {
    "default": "Allgemeine Antworten", "welcome": "Willkommen", "farewell": "Abschied",
    "birthday": "Geburtstagsgrüße", "message_edit": "Nachricht bearbeitet",
    "message_delete": "Nachricht gelöscht", "moderation": "Moderation", "logs": "Serverprotokoll",
    "notify_youtube": "YouTube-Video", "notify_youtube_live": "YouTube-Livestream", "notify_twitch": "Twitch-Livestream",
    "notify_tiktok": "TikTok-Video", "rank": "Rangkarte", "help": "Hilfe", "settings": "Einstellungen",
}
TEMPLATE_LABELS.update({"ping": "Befehl: Status", "setup": "Befehl: Einstellungen", "link": "Befehl: Profillink ändern", "quelle": "Befehl: Inhaltsquelle", "rollen": "Befehl: Stufenrolle", "ban": "Befehl: Bannen", "unban": "Befehl: Entbannen", "timeout": "Befehl: Stummschalten", "congratulate": "Befehl: Persönlicher Glückwunsch"})
TEMPLATE_LABELS.update({key: f"Profillink: {key.title()}" for key in ("youtube", "twitch", "tiktok", "instagram", "twitter", "facebook", "discord", "playstation", "xbox", "nintendo", "linktree")})
TEMPLATE_LABELS.update({"kick": "Befehl: Kicken", "untimeout": "Befehl: Stummschaltung aufheben", "reinvite": "Befehl: Einladung"})
ICONS = {"default": "✦", "welcome": "👋", "farewell": "🚪", "birthday": "🎂", "message_edit": "✏️",
         "message_delete": "🗑️", "moderation": "🛡️", "logs": "📋", "youtube": "▶️", "youtube_live": "🔴",
         "twitch": "🟣", "tiktok": "🎵", "notify_youtube": "▶️", "notify_youtube_live": "🔴", "notify_twitch": "🟣", "notify_tiktok": "🎵", "rank": "📊", "help": "🧭", "settings": "⚙️"}
PLACEHOLDERS = {"title", "description", "name", "user_id", "server", "member_count", "bot", "date"}


@lru_cache(maxsize=1)
def editor_catalog():
    """Packaged catalogue, also served as JSON by the dashboard; no remote assets."""
    return json.loads(Path(__file__).with_name("editor_catalog.json").read_text(encoding="utf-8"))


def template_defaults(key, config=None):
    """Defaults retain live {description}; fictional sample values are never saved."""
    config = config or {}
    catalogue = editor_catalog()
    entry = catalogue["categories"].get(key, catalogue["categories"]["default"])
    template = deepcopy(entry["template"])
    if key == "default":
        template["color"] = config.get("color", template["color"])
    template["image_style"] = deepcopy(next(design["style"] for design in catalogue["designs"] if design["id"] == "layered"))
    return template


def sample_template_context(key, *, name="Mira", server="MittelKings Universe", bot="Jarvis"):
    """Deliberately fictional preview context, separated from live configuration."""
    catalogue = editor_catalog()
    entry = catalogue["categories"].get(key, catalogue["categories"]["default"])
    sample = deepcopy(entry["sample"])
    context = {"name": name, "server": server, "bot": bot, "user_id": "123456789012345678",
               "member_count": "128", "date": "25.10.2026", "title": sample["title"], "description": sample["description"]}
    context["title"] = context["title"].format_map(context)
    context["description"] = context["description"].format_map(context)
    return {**context, "fields": sample["fields"], "avatar": sample["avatar"], "image": sample["image"]}


def _validate_text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Vorlagentext muss Text mit höchstens {limit} Zeichen sein.")
    for _, field, spec, conversion in Formatter().parse(value):
        if field is not None and (field not in PLACEHOLDERS or spec or conversion):
            raise ValueError("Unbekannter Platzhalter. Erlaubt: " + ", ".join("{" + p + "}" for p in sorted(PLACEHOLDERS)))


def validate_templates(templates):
    if not isinstance(templates, dict) or len(templates) > 100:
        raise ValueError("Embed-Vorlagen müssen ein Objekt mit maximal 100 Einträgen sein.")
    for key, item in templates.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,40}", key) or not isinstance(item, dict):
            raise ValueError("Ungültiger Vorlagenname oder ungültiges Vorlagenobjekt.")
        unknown = set(item) - {"title", "description", "color", "footer", "image_url", "thumbnail_url", "fields", "author", "use_default_banner", "image_style", "section_divider"}
        if unknown:
            raise ValueError("Unbekannte Embed-Eigenschaften: " + ", ".join(sorted(unknown)))
        if 'section_divider' in item and type(item['section_divider']) is not bool:
            raise ValueError('Abschnittstrenner muss an oder aus sein.')
        if 'image_style' in item:
            from .image_cards import validate_style
            validate_style(item['image_style'])
        if 'use_default_banner' in item and type(item['use_default_banner']) is not bool:
            raise ValueError('Standardbanner muss an oder aus sein.')
        for field, limit in (("title", 256), ("description", 4000), ("footer", 1000), ("author", 256)):
            if field in item:
                _validate_text(item[field], limit)
        if "color" in item and not re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
            raise ValueError("Embed-Farbe bitte als #RRGGBB angeben.")
        for field in ("image_url", "thumbnail_url"):
            value = item.get(field, "")
            if not isinstance(value, str):
                raise ValueError("Bildadresse muss Text sein.")
            if value:
                parts = urlsplit(value)
                if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or len(value) > 1000 or any(c.isspace() for c in value):
                    raise ValueError("Bilder brauchen eine direkte öffentliche HTTPS-Adresse.")
        fields = item.get("fields", [])
        if not isinstance(fields, list) or len(fields) > 20:
            raise ValueError("Maximal 20 Embed-Felder verwenden.")
        for field in fields:
            if not isinstance(field, dict) or set(field) - {"name", "value", "inline"}:
                raise ValueError("Embed-Felder brauchen name, value und optional inline.")
            _validate_text(field.get("name", ""), 256)
            _validate_text(field.get("value", ""), 1024)
            if "inline" in field and not isinstance(field["inline"], bool):
                raise ValueError("inline muss wahr oder falsch sein.")


def infer_template(title):
    lowered = title.casefold()
    if "moderation" in lowered or any(w in lowered for w in ("bann", "entbann", "timeout")):
        return "moderation"
    if "nachricht gelöscht" in lowered:
        return "message_delete"
    if "nachricht bearbeitet" in lowered:
        return "message_edit"
    if "willkommen" in lowered:
        return "welcome"
    if "verlassen" in lowered:
        return "farewell"
    if "geburtstag" in lowered or "glückwunsch" in lowered:
        return "birthday"
    if "befehls" in lowered or "hilfe" in lowered:
        return "help"
    if "einstellung" in lowered:
        return "settings"
    return "default"


def build_embed(reply, c, member=None, template_key="default", context=None):
    """Bound every interpolated value to Discord limits, including total 6000 chars."""
    if template_key == "default":
        template_key = "rank" if reply.rank else infer_template(reply.title)
    template = c.get("embed_templates", {}).get(template_key, c.get("embed_templates", {}).get("default", {}))
    values = {"title": reply.title, "description": reply.text, "name": getattr(member, "display_name", "Mitglied"),
              "user_id": str(getattr(member, "id", "")), "server": getattr(getattr(member, "guild", None), "name", "Server"),
              "member_count": str(getattr(getattr(member, "guild", None), "member_count", "")), "bot": c["name"],
              "date": datetime.now(timezone.utc).strftime("%d.%m.%Y")}
    values.update(context or {})
    values = {k: discord.utils.escape_mentions(str(v)) for k, v in values.items()}
    def text(field, fallback, limit):
        raw = template.get(field, fallback)
        try:
            return raw.format_map(values)[:limit]
        except (ValueError, KeyError):
            return str(fallback).format_map(values)[:limit]
    if template_key in {"logs", "message_edit", "message_delete"} and "description" not in template:
        labels = {"Kanal": "💬 Kanal", "Nachricht": "✉️ Nachricht", "Autor": "👤 Autor", "Inhalt": "📝 Inhalt", "Vorher": "− Vorher", "Nachher": "+ Nachher", "Mitglied": "👤 Mitglied", "Rollen hinzugefügt": "➕ Rollen hinzugefügt", "Rollen entfernt": "➖ Rollen entfernt", "Spitzname": "🏷️ Spitzname"}
        values["description"] = re.sub(r"(?m)^(Kanal|Nachricht|Autor|Inhalt|Vorher|Nachher|Mitglied|Rollen hinzugefügt|Rollen entfernt|Spitzname):", lambda m: "**" + labels[m[1]] + ":**", values["description"])
    colors = {"welcome": "#57c99d", "farewell": "#e47d8c", "message_delete": "#f3b35d", "message_edit": "#65b4ec", "moderation": "#a18aee", "birthday": "#ecb15f"}
    embed = discord.Embed(title=text("title", "{title}", 256), description=text("description", "{description}", 4000),
                          color=int(template.get("color", colors.get(template_key, c["color"])).lstrip("#"), 16), timestamp=datetime.now(timezone.utc))
    if reply.timestamp:
        try:
            embed.timestamp = datetime.fromisoformat(reply.timestamp)
        except ValueError:
            pass
    embed.set_author(name=text("author", f"{ICONS.get(template_key, '✦')} " + c["name"] + " · " + TEMPLATE_LABELS.get(template_key, "Community"), 256))
    embed.set_footer(text=text("footer", "{bot} • MittelKings Universe", 1000))
    for name, value, inline in reply.fields[:25]:
        embed.add_field(name=discord.utils.escape_mentions(name)[:256], value=discord.utils.escape_mentions(str(value))[:1024] or "—", inline=inline)
    for field in template.get("fields", []):
        if len(embed.fields) >= 25:
            break
        embed.add_field(name=field["name"].format_map(values)[:256] or "—", value=field["value"].format_map(values)[:1024] or "—", inline=field.get("inline", False))
    divider_default = template_key in {"welcome", "farewell", "birthday", "logs", "moderation", "message_edit", "message_delete"}
    if template.get("section_divider", divider_default) and embed.fields and embed.description:
        embed.description = embed.description.rstrip()[:3975] + "\n\n───────────────"
    # Discord enforces the combined embed limit as well as individual fields.
    while len(embed) > 5900 and embed.fields:
        embed.remove_field(len(embed.fields) - 1)
    if len(embed) > 5900:
        embed.description = (embed.description or "")[:max(0, 5900 - (len(embed) - len(embed.description or "")))]
    avatar = getattr(getattr(member, "display_avatar", None), "url", None)
    thumbnail = template.get("thumbnail_url") or (str(avatar) if isinstance(avatar, str) else "")
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if template.get("image_url"):
        embed.set_image(url=template["image_url"])
    return embed
