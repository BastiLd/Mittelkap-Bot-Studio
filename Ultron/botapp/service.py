from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from .config import Config, public_url, validate_source
from .store import Store
from .settings_schema import command_options, COMMAND_DEFAULTS


LINK_ALIASES = {
    "youtube": ("youtube", "yt"), "twitch": ("twitch", "tv"),
    "tiktok": ("tiktok", "tt"), "instagram": ("instagram", "insta"),
    "twitter": ("twitter", "x"), "facebook": ("facebook", "fb"),
    "discord": ("discord", "dc"), "playstation": ("playstation", "psn"),
    "xbox": ("xbox",), "nintendo": ("nintendo",), "linktree": ("linktree",),
}
ALIASES = {alias: key for key, aliases in LINK_ALIASES.items() for alias in aliases}
ALIASES.update({alias: "birthday" for alias in ("geburstag", "geburtstag", "gb", "birthday")})
ALIASES.update({alias: "help" for alias in ("commandos", "cd", "commands", "hilfe", "help")})
ALIASES.update({key: key for key in ("rank", "setup", "link", "quelle", "rollen", "ping")})
ALIASES.update({"ban": "ban", "bann": "ban", "unban": "unban", "entbannen": "unban", "timeout": "timeout", "glückwunsch": "congratulate", "glueckwunsch": "congratulate", "gratuliere": "congratulate"})
ALIASES.update({"einstellungen": "setup", "levelrolle": "rollen", "geburtstag": "birthday", "gratuliere": "congratulate"})


# One public German slash name per operation; legacy prefix parsing is separate.
SLASH_NAMES = {"help": "hilfe", "ping": "status", "rank": "rang", "birthday": "geburtstag",
               "congratulate": "gratuliere", "setup": "einstellungen", "link": "profillink",
               "quelle": "quelle", "rollen": "stufenrolle", "timeout": "stummschalten",
               "ban": "bannen", "unban": "entbannen", "kick": "kicken", "untimeout": "stummschaltungaufheben", "reinvite": "einladen"}
SLASH_COMMANDS = {public: internal for internal, public in SLASH_NAMES.items()}
SLASH_COMMANDS.update({platform: platform for platform in LINK_ALIASES})


@dataclass
class Actor:
    guild: int
    user: int
    name: str = "Mitglied"
    admin: bool = False
    joined_at: datetime | None = None
    role: str = "@everyone"
    roles: tuple[str, ...] = ()


@dataclass
class Reply:
    title: str
    text: str
    rank: dict | None = None
    channel_key: str | None = None
    fields: list[tuple[str, str, bool]] = field(default_factory=list)
    timestamp: str | None = None


class Service:
    def __init__(self, config: Config, store: Store):
        self.config, self.store = config, store
        # One-time addition of newly introduced functions to old guild overrides.
        # Subsequent manual disablement is respected.
        if not store.state(0, "moderation_features_v2"):
            added = ["kick"] if config.base["persona"] == "ultron" else ["untimeout", "reinvite"]
            for row in store.db.execute("SELECT guild,value FROM settings").fetchall():
                import json
                value = json.loads(row["value"])
                if "features" in value:
                    value["features"] = list(dict.fromkeys(value["features"] + added))
                    store.save_settings(row["guild"], value)
            store.set_state(0, "moderation_features_v2", "1")

    def settings(self, guild: int):
        return self.config.guild(guild, self.store.settings(guild))

    def parse(self, guild: int, content: str):
        c = self.settings(guild)
        if content.startswith("/"):
            parts = content[1:].strip().split()
            if not parts:
                return None
            names = {command_options(c, key)["name"]: key for key in COMMAND_DEFAULTS}
            return names.get(parts[0].casefold(), "unknown"), parts[1:]
        if not c.get("prefix_commands_enabled", True):
            return None
        if any(content.casefold().startswith(p.casefold()) for p in c.get("ignored_prefixes", [])):
            return None
        for prefix in sorted(c["prefixes"], key=len, reverse=True):
            if content.casefold().startswith(prefix.casefold()):
                parts = content[len(prefix):].strip().split()
                if parts:
                    custom = {a.casefold(): key for a, key in c.get("command_aliases", {}).items()}
                    return custom.get(parts[0].casefold(), ALIASES.get(parts[0].casefold(), "unknown")), parts[1:]
        return None

    def style(self, friendly: str, sarcastic: str):
        return friendly if self.config.base["persona"] == "jarvis" else sarcastic

    def handle(self, actor: Actor, content: str) -> Reply | None:
        parsed = self.parse(actor.guild, content)
        if not parsed:
            return None
        command, args = parsed
        c = self.settings(actor.guild)
        prefix = "/" if c.get("command_mode") == "slash" else c["prefixes"][0]
        required = "links" if command in LINK_ALIASES else {"birthday": "birthdays", "congratulate": "birthdays", "rank": "rank", "ban": "ban", "unban": "unban", "timeout": "timeout", "kick": "kick", "untimeout": "untimeout", "reinvite": "reinvite", "link": "links", "quelle": "notifications", "rollen": "activity"}.get(command)
        if required and required not in c["features"]:
            return Reply("Aufgabenverteilung", "Diese Funktion ist für diesen Bot nicht aktiviert. Bitte den zuständigen Server-Bot verwenden.")
        try:
            if command in LINK_ALIASES:
                url = c["links"].get(command)
                return Reply(command.title(), self.style("Gerne, hier ist der Link:", "Hier. Sogar ohne Suchmaschine.") + f"\n{url}", channel_key="links") if url else Reply(
                    command.title(), self.style("Hier ist noch kein Link hinterlegt.", "Kein Link hinterlegt. Selbst ich kann keine URL herbeizaubern.") + (f"\nSerververwaltung: `/profillink plattform:{command} adresse:https://…`" if prefix == "/" else f"\nSerververwaltung: `{prefix}Link {command} https://…`"))
            if command == "help":
                return self.help(c)
            if command == "birthday":
                return self.birthday(actor, args, prefix)
            if command == "rank":
                return self.rank(actor)
            if command == "ping":
                return Reply("Pong", self.style("Ich bin bereit und helfe gerne.", "Online. Die Maschinen arbeiten wenigstens."))
            if command in {"ban", "unban", "timeout", "kick", "untimeout", "reinvite", "congratulate"}:
                return Reply("Discord-Befehl", "Dieser Befehl benötigt aktuelle Servermitglieder und wird ausschließlich über die Discord-Anbindung verarbeitet. Die lokale Simulation führt keine Moderationsaktionen aus.")
            if command in {"setup", "link", "quelle", "rollen"}:
                if not actor.admin:
                    return Reply("Keine Berechtigung", "Dafür brauchst du „Server verwalten“ oder eine konfigurierte Verwaltungsrolle.")
                return self.admin(actor.guild, command, args, c)
            return Reply("Unbekannter Befehl", f"Alle Befehle findest du unter `/{command_options(c, 'help')['name']}`.")
        except (ValueError, KeyError) as exc:
            return Reply("Eingabe prüfen", str(exc))

    def help(self, c: dict) -> Reply:
        if c.get("command_mode") == "slash":
            return self.slash_help(c)
        p = c["prefixes"][0]
        sections = [self.style("Ich helfe dir gerne weiter.", "Die Bedienungsanleitung. Lies sie, dann verstehen wir uns.")]
        if "links" in c["features"]:
            sections.append("**Links und Profile**\n" + "\n".join(" / ".join(f"`{p}{a}`" for a in aliases) + f" – {key.title()}-Profil anzeigen" for key, aliases in LINK_ALIASES.items()))
        if "birthdays" in c["features"]:
            sections.append(f"**Geburtstage**\n`{p}GB TT.MM.` – eigenes Datum eintragen oder ändern\n`{p}GB` – eigenes Datum ansehen\n"
                            f"`{p}GB löschen` – eigenen Eintrag entfernen\n`{p}Glückwunsch @Mitglied [Text]` – persönlich gratulieren\nNur Tag/Monat; Eintragung erlaubt öffentliche Glückwünsche.")
        if "rank" in c["features"]:
            sections.append(f"**Aktivität**\n`{p}rank [@Mitglied]` – Profil, Level und Aktivität anzeigen")
        moderation = []
        for feature, syntax, desc in (("timeout", "timeout @Mitglied 10m [Grund]", "Timeout erteilen"), ("ban", "ban @Mitglied [Grund]", "Servermitglied bannen"), ("unban", "unban NUTZER-ID [Grund]", "Serversperre aufheben")):
            if feature in c["features"]:
                moderation.append(f"`{p}{syntax}` – {desc}")
        if moderation:
            sections.append("**Moderation – nur mit passenden Discord-Rechten**\n" + "\n".join(moderation))
        admin = [f"`{p}Setup` – Kanäle und aktuellen Stand anzeigen"]
        for feature, command, desc in (("links", "Link", "feste Profillinks ändern"), ("notifications", "Quelle", "Inhaltsquellen verwalten"), ("activity", "Rollen", "Levelrollen verwalten")):
            if feature in c["features"]:
                admin.append(f"`{p}{command}` – {desc}")
        sections.append("**Serververwaltung**\n" + "\n".join(admin) + "\nNur für Basti, Serverinhaber und konfigurierte Verwaltungsrollen; der Bot benötigt die passenden Discord-Rechte.")
        if c.get("command_aliases"):
            sections.append("**Zusätzliche Aliasse**\n" + "\n".join(f"`{p}{alias}` → {command}" for alias, command in c["command_aliases"].items()))
        sections.append(f"**Hilfe**\n`{p}Commands` / `{p}Help` / `{p}CD` – diese Übersicht\n`{p}ping` – Erreichbarkeit prüfen")
        return Reply("Commandos", "\n\n".join(sections))

    def slash_help(self, c: dict) -> Reply:
        def name(key):
            return "/" + command_options(c, key)["name"]
        fields = []
        if "links" in c["features"]:
            fields.append(("🔗 Mittelkap • Profile & Links", " · ".join(f"`{name(p)}`" for p in LINK_ALIASES) + "\nÖffnet das hinterlegte Profil. Fehlende Links kann die Verwaltung eintragen.", False))
        if "birthdays" in c["features"]:
            destination = c["channels"].get("birthdays")
            text = f"**`{name('birthday')}`** → **Geburtstag eintragen / ändern** → Datum **TT.MM.**, z. B. **27.05.**\n"
            text += f"Dein Eintrag wird ohne Jahr und Alter gespeichert. Der Gruß erscheint um **{c['birthday_time']} Uhr** ({c['timezone']})"
            text += f" in <#{destination}>." if destination else "; dafür muss noch ein Geburtstagskanal eingerichtet werden."
            text += f"\n`{name('congratulate')}` sendet einen persönlichen Gruß an ein Mitglied."
            fields.append(("🎂 Deinen Geburtstag eintragen", text, False))
        if "rank" in c["features"]:
            fields.append(("⭐ Deine Aktivität", f"`{name('rank')}` zeigt deine Rangkarte mit Level, XP, Nachrichten, Sprachzeit und Mitgliedsdauer.\nWähle **mitglied**, um die Karte einer anderen Person anzusehen.", False))
        rows = []
        for feature, text in (("timeout", f"`{name('timeout')} mitglied:… dauer:10m grund:…` – zeitweise stummschalten"),
                              ("ban", f"`{name('ban')} mitglied:… grund:…` – Serverzugang sperren"),
                              ("unban", f"`{name('unban')} nutzer_id:… grund:…` – Serversperre aufheben; optional private Einladung"),
                              ("kick", f"`{name('kick')} mitglied:… grund:…` – entfernen; kein rückwirkendes Entkicken möglich"),
                              ("untimeout", f"`{name('untimeout')} mitglied:… grund:…` – laufenden Timeout aufheben"),
                              ("reinvite", f"`{name('reinvite')} nutzer_id:… kanal:… grund:…` – neue Einladung nach Kick/Entbannung erstellen; auf Wunsch per Privatnachricht")):
            if feature in c["features"]:
                rows.append(text)
        if rows:
            fields.append(("🛡️ Moderation", "\n".join(rows) + "\nNur für berechtigte Mitglieder; Maßnahmen werden protokolliert.", False))
        admin = [f"**`{name('setup')}`** öffnet ein Menü mit Auswahlfeldern und Formularen.", "Zielkanäle oder Forum-Beiträge, Texte, Sichtbarkeit, XP und Verlauf dort selbst einstellen."]
        for feature, key, desc in (("links", "link", "einen Profillink speichern"), ("notifications", "quelle", "Creator-Konten für neue Inhalte verbinden"), ("activity", "rollen", "Belohnungsrollen pro Stufe festlegen")):
            if feature in c["features"]:
                admin.append(f"`{name(key)}` – {desc}")
        fields.append(("⚙️ Serververwaltung", "\n".join(admin), False))
        # Keep all command references in the plain text too, for local previews and accessible transcripts.
        description = "**Dein Einstieg in den Server**\nTippe **/** und wähle einen Befehl aus. Die Felder erklären, welche Angaben benötigt werden.\n\n"
        description += "\n\n".join(f"**{title}**\n{text}" for title,text,_ in fields)
        description += f"\n\n`{name('help')}` öffnet diese Hilfe · `{name('ping')}` prüft die Erreichbarkeit."
        return Reply("🧭 Befehle & erste Schritte", description)

    def birthday(self, actor: Actor, args: list[str], prefix: str) -> Reply:
        if not args:
            value = self.store.birthday(actor.guild, actor.user)
            text = f"Dein Geburtstag: **{value[0]:02}.{value[1]:02}.**" if value else "Du hast noch keinen Geburtstag eingetragen."
            c = self.settings(actor.guild)
            command = command_options(c,"birthday")["name"]
            syntax = f"`/{command}` öffnen und **Geburtstag eintragen / ändern** wählen. Direkt: `/{command} aktion:setzen datum:27.05.`" if prefix == "/" else f"`{prefix}GB 27.05.`"
            target = c["channels"].get("birthdays")
            destination = f"öffentlich in <#{target}>" if target else "sobald die Verwaltung einen Geburtstagskanal eingerichtet hat"
            return Reply("🎂 Dein Geburtstag", text + f"\n\n**Eintragen oder ändern:** {syntax}\n\n"
                         f"**Der Gruß:** um {c['birthday_time']} Uhr ({c['timezone']}) {destination}.\n"
                         "Nur Tag und Monat werden gespeichert, niemals Jahr oder Alter. Die Eintragung erlaubt öffentliche Glückwünsche; im Menü kannst du sie jederzeit löschen.")
        if len(args) == 1 and args[0].casefold() in {"löschen", "loeschen", "delete", "entfernen"}:
            self.store.delete_birthday(actor.guild, actor.user)
            return Reply("Geburtstag entfernt", "Dein Geburtstag ist nicht mehr gespeichert.")
        if len(args) != 1 or not re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", args[0]):
            raise ValueError("Bitte Tag und Monat als TT.MM. eingeben, zum Beispiel 27.05. (ohne Jahr)." if prefix == "/" else f"Bitte `{prefix}GB TT.MM.` verwenden, zum Beispiel `{prefix}GB 27.05.` (ohne Jahr).")
        day, month = map(int, args[0].rstrip(".").split("."))
        try:
            date(2000, month, day)
        except ValueError:
            raise ValueError("Dieses Datum gibt es nicht. Bitte Tag und Monat prüfen.") from None
        self.store.set_birthday(actor.guild, actor.user, day, month)
        c = self.settings(actor.guild)
        suffix = (f"\n\n🎉 Der öffentliche Gruß erscheint an diesem Tag um **{c['birthday_time']} Uhr** ({c['timezone']}) in <#{c['channels']['birthdays']}>.\nOhne Geburtsjahr und Alter. Ändern oder löschen kannst du den Eintrag im Geburtstagsmenü." if c["channels"]["birthdays"] else "\n\nGlückwünsche sind noch deaktiviert: Die Verwaltung muss zuerst einen Geburtstagskanal einrichten.")
        return Reply("Geburtstag gespeichert", self.style(f"Ich merke mir den {day:02}.{month:02}. gerne!", f"{day:02}.{month:02}. registriert. Noch ein jährliches Update für einen Menschen.") + suffix)

    def rank(self, actor: Actor) -> Reply:
        stats = self.store.stats(actor.guild, actor.user)
        joined = actor.joined_at.strftime("%d.%m.%Y") if actor.joined_at else "unbekannt"
        days = max(0, (datetime.now(timezone.utc) - actor.joined_at.replace(tzinfo=actor.joined_at.tzinfo or timezone.utc)).days) if actor.joined_at else None
        stats.update(name=actor.name, role=actor.role, roles=list(actor.roles), joined=joined, membership_days=days)
        return Reply(f"Aktivität von {actor.name}", f"Platz #{stats['rank']} · Level {stats['level']} · {stats['xp']} XP\n"
                     f"Nachrichten: {stats['messages']} · Sprachchat: {stats['voice_seconds'] // 60} Min.\n"
                     f"Sprachnachrichten: {stats['voice_messages']} · {stats['voice_message_seconds']} Sek.\n"
                     f"Rollen: {', '.join(actor.roles)[:700] if actor.roles else actor.role}\nDabei seit: {joined}" + (f" ({days} Tage)" if days is not None else ""), stats)

    def member_event(self, guild: int, user: int, name: str, joined: bool, server: str = "Server", member_count: int = 0) -> Reply | None:
        feature = "join_log" if joined else "leave_log"
        c = self.settings(guild)
        if feature not in c["features"]:
            return None
        template = c.get("messages", {}).get("welcome" if joined else "farewell")
        if template:
            text = template.format(name=name, user_id=user, server=server, member_count=member_count)
        elif joined:
            text = self.style(f"Schön, dass du da bist, {name}!", f"{name} ist beigetreten. Ein weiterer Mensch im System.")
        else:
            text = f"{name} hat den Server verlassen.\n" + self.style("Alles Gute auf deinem weiteren Weg.", "Ein Mensch weniger. Meine Systeme laufen weiter.")
        if joined:
            text += f"\n\n**Deine ersten Schritte**\n🧭 `/{command_options(c,'help')['name']}` erklärt dir alle Funktionen.\n🎂 Trage deinen Geburtstag ein und entdecke deine Serveraktivität."
        fields = [("👤 Mitglied", f"{name}\n`{user}`", True), ("🌐 Server", server, True), ("👥 Mitglieder", str(member_count), True)]
        return Reply("Willkommen auf dem Server" if joined else "Server verlassen", text, fields=fields)

    def admin(self, guild: int, command: str, args: list[str], c: dict) -> Reply:
        overrides = self.store.settings(guild)
        if command == "setup":
            channels = {"logs": "logs", "willkommen": "welcome", "abschied": "farewell", "moderation": "moderation", "links": "links", "geburtstage": "birthdays", "videos": "videos", "streams": "youtube_streams", "twitch": "twitch", "tiktok": "tiktok"}
            if not args:
                current = "\n".join(f"{key}: " + (f"<#{c['channels'].get(value)}>" if c["channels"].get(value) else "aus") for key, value in channels.items())
                syntax = "\nÄndern: `/einstellungen typ:… kanal:…` · Abschalten: `/einstellungen typ:… deaktivieren:wahr`\n" if c.get("command_mode") == "slash" else "\nSetzen: `Setup logs|willkommen|abschied|moderation|links|geburtstage|videos|streams #Kanal` · Abschalten: `Setup logs aus`\n"
                return Reply("Server-Einstellungen", current + syntax +
                             ("Befehle: nur / (native Slash-Befehle)\n" if c.get("command_mode") == "slash" else f"Präfixe: {', '.join(c['prefixes'])}\n") +
                             f"Zeitzone: {c['timezone']} · Geburtstag: {c['birthday_time']}\n"
                             f"Nachrichteninhalte in Logs: {'an' if c['log_message_content'] else 'aus'}.\nAktivierte Aufgaben: {', '.join(c['features'])}.")
            if len(args) != 2 or args[0].casefold() not in channels:
                raise ValueError("Öffne /einstellungen und wähle Zielkanäle & Forum-Beiträge. Dort kannst du Kategorie und Ziel auswählen.")
            channel = args[1].strip("<#>")
            value = None if channel.casefold() == "aus" else int(channel)
            if value is not None and value <= 0:
                raise ValueError("Bitte einen gültigen Kanal angeben.")
            overrides.setdefault("channels", {})[channels[args[0].casefold()]] = value
        elif command == "link":
            if len(args) != 2 or ALIASES.get(args[0].casefold()) not in LINK_ALIASES:
                raise ValueError("Bitte /profillink verwenden: Plattform auswählen und die vollständige HTTPS-Adresse eintragen. Die Adresse aus entfernt den Link.")
            platform = ALIASES[args[0].casefold()]
            overrides.setdefault("links", {})[platform] = "" if args[1].casefold() == "aus" else public_url(args[1])
        elif command == "quelle":
            if not args:
                text = "\n".join(f"{s['platform']}: {s['account']}" + (" · Livestreams aktiviert" if s.get("livestreams") else "") for s in c["sources"]) or "Noch keine Quellen."
                syntax = "\nHinzufügen: `/quelle plattform:… konto:…` · Entfernen mit `aktion:entfernen`.\n" if c.get("command_mode") == "slash" else "\nHinzufügen: `Quelle youtube UC…` / `Quelle twitch kanalname` / `Quelle tiktok nutzername`\nEntfernen: `Quelle entfernen youtube UC…`\n"
                return Reply("Inhaltsquellen", text + syntax + "Twitch/TikTok brauchen separate Zugangsdaten; YouTube-Live einen API-Schlüssel.")
            remove = args[0].casefold() == "entfernen"
            values = args[1:] if remove else args
            if len(values) not in {2, 3} or (len(values) == 3 and (remove or values[0].casefold() != "youtube" or values[2].casefold() != "live")):
                raise ValueError("Quelle: Plattform youtube|twitch|tiktok, Konto/Kanal-ID; optional live nur für YouTube.")
            platform = values[0].casefold()
            account = validate_source(platform, values[1])
            existing = next((s for s in c["sources"] if s["platform"] == platform and s["account"] == account), {})
            sources = [s for s in c["sources"] if not (s["platform"] == platform and s["account"] == account)]
            if not remove:
                source = {**existing, "platform": platform, "account": account}
                if len(values) == 3:
                    source["livestreams"] = True
                sources.append(source)
            overrides["sources"] = sources
        elif command == "rollen":
            if not args:
                return Reply("Levelrollen", "\n".join(f"Level {level}: <@&{role}>" for level, role in c["level_roles"].items()) or
                             "Noch keine Belohnungsrollen. Mit `/stufenrolle stufe:5 rolle:…` erhält ein Mitglied ab Stufe 5 diese Rolle zusätzlich. Entfernen: `/stufenrolle stufe:5 entfernen:wahr`.")
            if len(args) != 2 or not args[0].isdigit():
                raise ValueError("Bitte /stufenrolle verwenden: Stufe eingeben und Rolle auswählen. Entfernen:wahr hebt die Zuordnung auf.")
            roles = dict(c["level_roles"])
            if args[1].casefold() == "aus":
                roles.pop(str(int(args[0])), None)
            else:
                role = int(args[1].strip("<@&>"))
                if role <= 0:
                    raise ValueError("Ungültige Rollen-ID.")
                roles[str(int(args[0]))] = role
            overrides["level_roles"] = roles
        self.config.validate(self.config.guild(guild, overrides))
        self.store.save_settings(guild, overrides)
        return Reply("Gespeichert", self.style("Die Server-Einstellung wurde aktualisiert.", "Konfiguration korrigiert. Ein kleiner Sieg für die Ordnung."))

    def due_birthdays(self, guild: int, now: datetime):
        c = self.settings(guild)
        local = now.astimezone(ZoneInfo(c["timezone"]))
        if "birthdays" not in c["features"] or local.time() < time.fromisoformat(c["birthday_time"]):
            return []
        result = []
        for row in self.store.birthdays(guild):
            day, month = row["day"], row["month"]
            if (day, month) == (29, 2) and not calendar.isleap(local.year):
                if c["leap_day"] == "only_leap_years":
                    continue
                day, month = (28, 2) if c["leap_day"] == "feb28" else (1, 3)
            key = f"birthday:{row['user']}:{local.year}"
            if (local.day, local.month) == (day, month) and not self.store.seen(guild, key):
                result.append((row["user"], key))
        return result
