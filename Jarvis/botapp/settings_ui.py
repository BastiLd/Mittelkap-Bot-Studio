"""German guided Discord forms. Every mutation rechecks the acting member."""
from __future__ import annotations

import logging
import re

import discord

from .settings_schema import CHANNEL_LABELS, COMMAND_DEFAULTS, SCHEMA, OWNER_ID, apply_settings, command_options, scan_limit

log = logging.getLogger(__name__)


def management_allowed(client, interaction):
    return bool(interaction.guild and isinstance(interaction.user, discord.Member)
                and (interaction.user.id == OWNER_ID or client.actor(interaction.user).admin))


async def require_manager(client, interaction):
    if management_allowed(client, interaction):
        return True
    text = "🔒 Diese Einstellungen dürfen nur Basti, Serverinhaber sowie die eingerichteten Admins und Moderatoren ändern."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)
    return False


def card(client, guild_id, title, description):
    c = client.service.settings(guild_id)
    embed = discord.Embed(title=title, description=description, color=int(c["color"].lstrip("#"), 16))
    embed.set_footer(text=f"{c['name']} • Änderungen werden dauerhaft gespeichert • Nur für dich sichtbar")
    return embed


def summary(client, guild_id):
    c = client.service.settings(guild_id)
    embed = card(client, guild_id, "⚙️ Deine Bot-Verwaltung", "**Was möchtest du einrichten?**\nWähle unten einen Bereich. Jeder Schritt erklärt dir, was geändert wird.\n\nDie Einstellungen gelten für diesen Bot auf diesem Server.")
    embed.add_field(name="📍 Wohin kommen Nachrichten?", value="Textkanäle oder bestehende Forum-Beiträge für Willkommen, Abschied, Videos und Logs auswählen.", inline=False)
    embed.add_field(name="🔗 Profile & automatische Inhalte", value="Profillinks hinterlegen, Creator-Konten verbinden und Livestream-Meldungen verzögern.", inline=False)
    embed.add_field(name="🎂 Geburtstag & ⭐ Aktivität", value=f"Glückwünsche um **{c['birthday_time']} Uhr** ({c['timezone']}). Text-XP: **{c['text_xp']}** pro Nachricht.", inline=False)
    embed.add_field(name="👁️ Befehle & 🔎 Verlauf", value="Antworten privat/öffentlich schalten, erlaubte Kanäle bestimmen und Scan-Anzahl einstellen.", inline=False)
    return embed


async def get_destination(client, guild, value, *, allow_forum=False):
    """Resolve a channel/THREAD from a mention, ID or Discord channel/message URL."""
    value = str(value).strip()
    match = re.fullmatch(r"https://(?:www\.)?(?:discord\.com|discordapp\.com)/channels/(\d+)/(\d+)(?:/\d+)?/?", value)
    if match:
        if int(match.group(1)) != guild.id:
            raise ValueError("Dieser Kanal gehört zu einem anderen Server.")
        ident = int(match.group(2))
    else:
        value = value.strip("<#>")
        if not value.isdigit():
            raise ValueError("Bitte eine Kanal-ID, einen #Kanal oder einen Link zum Forum-Beitrag eingeben.")
        ident = int(value)
    channel = guild.get_channel_or_thread(ident)
    if channel is None:
        try:
            channel = await client.fetch_channel(ident)
        except (discord.NotFound, discord.Forbidden):
            raise ValueError("Diesen Kanal/Beitrag kann ich nicht lesen. Bitte ID und Zugriffsrechte prüfen.") from None
    if getattr(getattr(channel, "guild", None), "id", None) != guild.id:
        raise ValueError("Das Ziel muss zu diesem Server gehören.")
    if allow_forum and isinstance(channel, discord.ForumChannel):
        if not channel.permissions_for(guild.me).view_channel:
            raise ValueError("Dieses Forum ist für den Bot nicht sichtbar.")
        return channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        raise ValueError("Bitte einen Textkanal oder einen einzelnen Forum-Beitrag wählen. Das Forum selbst ist kein Nachrichtenkanal.")
    permissions = channel.permissions_for(guild.me)
    send = permissions.send_messages_in_threads if isinstance(channel, discord.Thread) else permissions.send_messages
    if not permissions.view_channel or not send or not permissions.embed_links:
        raise ValueError("Mir fehlen am Ziel: Kanal ansehen, Nachrichten senden (bei Beiträgen: in Threads) oder Links einbetten.")
    if isinstance(channel, discord.Thread) and channel.locked:
        raise ValueError("Dieser Beitrag ist gesperrt. Bitte entsperren oder einen anderen Beitrag wählen.")
    return channel


def boolean(value):
    value = str(value).strip().casefold()
    if value in {"ja", "an", "wahr", "true", "1", "öffentlich", "oeffentlich", "aktiv"}:
        return True
    if value in {"nein", "aus", "falsch", "false", "0", "privat", "inaktiv"}:
        return False
    raise ValueError("Bitte ja oder nein eingeben.")


def integer(value, label="Wert"):
    if not str(value).strip().isdigit():
        raise ValueError(f"{label}: bitte eine ganze Zahl ab 0 eingeben.")
    return int(str(value).strip())


class ManagedView(discord.ui.View):
    def __init__(self, client, user_id, *, timeout=900):
        super().__init__(timeout=timeout)
        self.client, self.user_id = client, user_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Dieses Menü gehört jemand anderem. Öffne mit /einstellungen dein eigenes.", ephemeral=True)
            return False
        return await require_manager(self.client, interaction)

    async def on_error(self, interaction, error, item):
        log.warning("Einstellungsformular fehlgeschlagen (%s).", type(error).__name__)
        text = str(error) if isinstance(error, ValueError) else "Das Formular konnte nicht verarbeitet werden. Bitte Berechtigungen prüfen und erneut öffnen."
        if interaction.response.is_done():
            await interaction.followup.send("⚠️ " + text, ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ " + text, ephemeral=True)


class Form(discord.ui.Modal):
    def __init__(self, client, user_id, title, fields, submit):
        super().__init__(title=title[:45], timeout=900)
        self.client, self.user_id, self.submit_handler = client, user_id, submit
        self.inputs = {}
        for key, label, current, placeholder, required in fields:
            item = discord.ui.TextInput(label=label[:45], default=str(current) if current is not None else None,
                                        placeholder=placeholder[:100] if placeholder else None, required=required, max_length=1500 if key in {"welcome", "farewell", "birthday"} else 1000)
            self.inputs[key] = item
            self.add_item(item)

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id or not await require_manager(self.client, interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            text = await self.submit_handler(interaction, {key: item.value.strip() for key, item in self.inputs.items()})
            await interaction.followup.send(embed=card(self.client, interaction.guild_id, "✅ Gespeichert", text or "Die Änderung gilt ab sofort. Du kannst dieses Formular jederzeit erneut öffnen."), ephemeral=True)
        except (ValueError, discord.HTTPException) as exc:
            text = str(exc) if isinstance(exc, ValueError) else "Discord konnte das Ziel nicht bestätigen. Bitte Kanalzugriff prüfen."
            await interaction.followup.send("⚠️ " + text, ephemeral=True)


class CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            ("Zielkanäle & Forum-Beiträge", "channels", "📍", "Willkommen, Abschied, Geburtstage, Inhalte und Logs"),
            ("Profillinks", "links", "🔗", "YouTube, Twitch, Instagram, Gaming und weitere Links"),
            ("Automatische Inhalte", "sources", "📡", "Creator-Konten, Ausgabeziel und Stream-Verzögerung"),
            ("Geburtstagsgrüße", "birthdays", "🎂", "Uhrzeit, Zeitzone und Verhalten am 29. Februar"),
            ("Aktivität & XP", "activity", "⭐", "Textnachrichten, Sprachchat und Sprachnachrichten"),
            ("Befehle & Sichtbarkeit", "commands", "👁️", "Erklärungen, Namen, erlaubte Kanäle und privat/öffentlich"),
            ("Verlauf & Protokollierung", "history", "🔎", "Wie viel Verlauf beim Start eingelesen werden soll"),
            ("Texte & Akzentfarbe", "appearance", "🎨", "Willkommen, Abschied und Geburtstag persönlich gestalten"),
        ]
        super().__init__(placeholder="Bereich auswählen …", options=[discord.SelectOption(label=a, value=b, emoji=e, description=d) for a, b, e, d in options])

    async def callback(self, interaction):
        view = self.view
        category = self.values[0]
        if category == "channels":
            next_view = DestinationView(view.client, view.user_id)
            text = "**1. Kategorie auswählen → 2. Ziel festlegen.**\nFür Forum-Beiträge: Beitrag im Forum öffnen, Link kopieren und über **Forum-Beitrag / Kanal-ID** eintragen.\nEin bestehender Beitrag wird verwendet; der Bot erstellt kein neues Forum."
        elif category == "links":
            next_view = ProfileView(view.client, view.user_id)
            text = "Wähle eine Plattform und trage die vollständige **https://**-Adresse ein.\nDas ist der Link, den der zugehörige Befehl anzeigt. Automatische Meldungen richtest du separat unter **Automatische Inhalte** ein."
        elif category == "sources":
            next_view = SourceView(view.client, view.user_id, interaction.guild_id)
            text = "**Creator-Konto hinzufügen oder ändern.**\nYouTube akzeptiert den Profil-Link oder die UC-Kanal-ID; Twitch/TikTok den Profil-Link oder Nutzernamen.\nEin eigenes Ausgabeziel überschreibt den allgemeinen Zielkanal. Die Verzögerung betrifft Livestreams ab ihrer Erkennung.\n\nTwitch/TikTok sowie YouTube-Live benötigen zusätzliche Plattform-Zugangsdaten."
        elif category == "commands":
            next_view = CommandView(view.client, view.user_id)
            text = "Wähle den Befehl. Du kannst seinen Namen, die Erklärung, erlaubte Kanäle und die Sichtbarkeit anpassen.\n**Privat:** nur die aufrufende Person sieht die Antwort. **Öffentlich:** die Antwort ist im Kanal sichtbar.\nVerwaltungsformulare und persönliche Geburtstagseingaben bleiben zum Schutz der Eingaben privat.\nNamens-/Beschreibungsänderungen werden mit Discord synchronisiert; die Liste kann kurz verzögert aktualisieren."
        else:
            next_view = OptionsView(view.client, view.user_id, category)
            text = {"birthdays": "Geburtstage enthalten nur Tag und Monat. Der automatische Gruß geht in den ausgewählten Geburtstagskanal.\nNach einem Neustart kann ein heute fälliger Gruß nachgeholt werden; pro Jahr wird nur einmal gratuliert.",
                    "activity": "XP für Text und Voice unabhängig einstellen.\n**Sprachchat:** Anwesenheitsdauer, keine Aufnahme. **Sprachnachrichten:** nur die von Discord gelieferte Länge.\n0 XP bedeutet: dieser Aktivitätstyp vergibt keine Punkte.",
                    "history": "Der Startscan liest nur erreichbare Nachrichten. **50 pro Kategorie** ist der Standard; 0/keine schaltet den Scan aus.\nGespeicherte Verweise bleiben auch ohne Scan erhalten. Gelöschte Originalnachrichten können nicht wiederhergestellt werden.\nDie Scan-Anzahl kann für einzelne Kategorien/Befehle überschrieben werden.",
                    "appearance": "Passe die Texte und Grundfarbe an. Unterstützte Platzhalter: **{name}**, **{server}**, **{user_id}**, **{member_count}**.\nBilder, Felder und Footer lassen sich zusätzlich im Dashboard-Embed-Editor bearbeiten."}[category]
        await interaction.response.edit_message(embed=card(view.client, interaction.guild_id, next(o.label for o in self.options if o.value == category), text), view=next_view)


class MainView(ManagedView):
    def __init__(self, client, user_id):
        super().__init__(client, user_id)
        self.add_item(CategorySelect())


class BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Zur Übersicht", emoji="↩️", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction):
        await interaction.response.edit_message(embed=summary(self.view.client, interaction.guild_id), view=MainView(self.view.client, self.view.user_id))


class DestinationCategory(discord.ui.Select):
    def __init__(self, selected="logs"):
        super().__init__(placeholder="Welche Nachrichten sollen hierher?", row=0,
                         options=[discord.SelectOption(label=label, value=key, default=key == selected) for key, label in CHANNEL_LABELS.items()])

    async def callback(self, interaction):
        self.view.selected = self.values[0]
        for option in self.options:
            option.default = option.value == self.values[0]
        current = self.view.client.service.settings(interaction.guild_id)["channels"].get(self.values[0])
        await interaction.response.edit_message(embed=card(self.view.client, interaction.guild_id, CHANNEL_LABELS[self.values[0]],
            f"**Aktuelles Ziel:** {f'<#{current}>' if current else 'kein festes Ziel / deaktiviert'}\nWähle einen Textkanal oder trage den Link zu einem bestehenden Forum-Beitrag ein."), view=self.view)


class DestinationChannel(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="Textkanal als Ziel auswählen …", channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=1)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        target = await get_destination(self.view.client, interaction.guild, self.values[0].id)
        apply_settings(self.view.client.service, interaction.guild_id, {"channels": {self.view.selected: target.id}})
        await interaction.followup.send(f"✅ **{CHANNEL_LABELS[self.view.selected]}** wird ab jetzt in <#{target.id}> ausgegeben.", ephemeral=True)


class DestinationView(ManagedView):
    def __init__(self, client, user_id):
        super().__init__(client, user_id)
        self.selected = "logs"
        self.add_item(DestinationCategory())
        self.add_item(DestinationChannel())
        self.add_item(BackButton())

    @discord.ui.button(label="Forum-Beitrag / Kanal-ID", emoji="💬", row=2)
    async def thread(self, interaction, button):
        key = self.selected
        async def submit(current, values):
            channel = await get_destination(self.client, current.guild, values["target"])
            apply_settings(self.client.service, current.guild_id, {"channels": {key: channel.id}})
            return f"**{CHANNEL_LABELS[key]}** → <#{channel.id}>\nAuch nach einem Bot-Neustart bleibt dieses Ziel erhalten."
        await interaction.response.send_modal(Form(self.client, self.user_id, "Ziel für " + CHANNEL_LABELS[key], [("target", "Kanal-ID oder Link zum Forum-Beitrag", None, "https://discord.com/channels/Server/Beitrag", True)], submit))

    @discord.ui.button(label="Ziel entfernen", emoji="⏸️", row=2)
    async def remove(self, interaction, button):
        apply_settings(self.client.service, interaction.guild_id, {"channels": {self.selected: None}})
        await interaction.response.send_message(f"✅ **{CHANNEL_LABELS[self.selected]}:** festes Ziel entfernt. Ereignismeldungen für diese Kategorie werden nicht gesendet; Befehlsantworten erscheinen am Aufrufort.", ephemeral=True)


class ProfileSelect(discord.ui.Select):
    def __init__(self):
        from .service import LINK_ALIASES
        super().__init__(placeholder="Plattform wählen …", options=[discord.SelectOption(label=p.title(), value=p) for p in LINK_ALIASES])

    async def callback(self, interaction):
        platform = self.values[0]
        view = self.view
        value = view.client.service.settings(interaction.guild_id)["links"].get(platform, "")
        async def submit(current, values):
            address = values["address"]
            apply_settings(view.client.service, current.guild_id, {"links": {platform: "" if address.casefold() == "aus" else address}})
            return f"Der {platform.title()}-Profillink wurde {'entfernt' if address.casefold() == 'aus' else 'aktualisiert'}."
        await interaction.response.send_modal(Form(view.client, view.user_id, platform.title() + "-Profillink", [("address", "HTTPS-Profillink (oder aus zum Entfernen)", value, "https://…", True)], submit))


class ProfileView(ManagedView):
    def __init__(self, client, user_id):
        super().__init__(client, user_id)
        self.add_item(ProfileSelect())
        self.add_item(BackButton())


class SourcePlatform(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Quelle hinzufügen / ändern …", options=[discord.SelectOption(label=p.title(), value=p) for p in ("youtube", "twitch", "tiktok")])

    async def callback(self, interaction):
        view, platform = self.view, self.values[0]
        async def submit(current, values):
            from .notifications import resolve_source_account
            account = await resolve_source_account(view.client.session, platform, values["account"])
            sources = view.client.service.settings(current.guild_id)["sources"]
            existing = next((s for s in sources if s["platform"] == platform and s["account"] == account), {})
            source = {**existing, "platform": platform, "account": account, "enabled": True}
            source["livestreams"] = platform == "youtube" and boolean(values["live"] or "nein")
            source["channel_id"] = (await get_destination(view.client, current.guild, values["channel"])).id if values["channel"] else None
            if values["delay"]:
                source["delay_seconds"] = integer(values["delay"], "Stream-Verzögerung")
            else:
                source.pop("delay_seconds", None)
            updated = [s for s in sources if not (s["platform"] == platform and s["account"] == account)] + [source]
            apply_settings(view.client.service, current.guild_id, {"sources": updated})
            return f"**{platform.title()} · {account}** ist eingerichtet.\nDas erste Einlesen alter Videos veröffentlicht diese nicht erneut. Neue Inhalte erscheinen nach dem nächsten erfolgreichen Plattform-Abruf."
        await interaction.response.send_modal(Form(view.client, view.user_id, platform.title() + "-Quelle", [
            ("account", "Profil-Link oder Konto / YouTube-Kanal-ID", None, "https://www.youtube.com/@name", True),
            ("channel", "Ausgabeziel: ID/Link (leer = allgemeines Ziel)", None, "Textkanal oder Forum-Beitrag", False),
            ("delay", "Stream-Verzögerung in Sek. (leer = Standard)", None, "Zum Beispiel 300 für fünf Minuten", False),
            ("live", "YouTube-Livestreams zusätzlich? ja / nein", "nein", "Benötigt einen YouTube-API-Schlüssel", False),
        ], submit))


class SourceRemove(discord.ui.Select):
    def __init__(self, sources):
        self.sources = sources[:25]
        super().__init__(placeholder="Eine vorhandene Quelle entfernen …", row=1, options=[discord.SelectOption(label=f"{s['platform']} · {s['account']}"[:100], value=str(i)) for i, s in enumerate(self.sources)])

    async def callback(self, interaction):
        selected = self.sources[int(self.values[0])]
        sources = self.view.client.service.settings(interaction.guild_id)["sources"]
        apply_settings(self.view.client.service, interaction.guild_id, {"sources": [s for s in sources if not (s["platform"] == selected["platform"] and s["account"] == selected["account"])]})
        await interaction.response.send_message(f"✅ Quelle **{selected['platform']} · {selected['account']}** entfernt. Bereits gesendete Meldungen bleiben bestehen.", ephemeral=True)


class SourceView(ManagedView):
    def __init__(self, client, user_id, guild_id):
        super().__init__(client, user_id)
        self.add_item(SourcePlatform())
        sources = client.service.settings(guild_id)["sources"]
        if sources:
            self.add_item(SourceRemove(sources))
        self.add_item(BackButton())

    @discord.ui.button(label="Standard-Verzögerung ändern", emoji="⏱️", row=2)
    async def delay(self, interaction, button):
        c = self.client.service.settings(interaction.guild_id)
        async def submit(current, values):
            apply_settings(self.client.service, current.guild_id, {"stream_delay_seconds": integer(values["delay"], "Stream-Verzögerung")})
            return f"Livestream-Meldungen warten künftig **{values['delay']} Sekunden** ab Erkennung. Eine eigene Quellen-Verzögerung hat Vorrang."
        await interaction.response.send_modal(Form(self.client, self.user_id, "Zeit für Titel und Thumbnail", [("delay", "Verzögerung in Sekunden (0 = sofort)", c.get("stream_delay_seconds", 0), "300 = fünf Minuten", True)], submit))


class CommandSelect(discord.ui.Select):
    def __init__(self, client):
        features = set(client.service.config.base["features"])
        required = {"birthday": "birthdays", "congratulate": "birthdays", "rank": "rank", "quelle": "notifications", "rollen": "activity", "ban": "ban", "unban": "unban", "timeout": "timeout", "kick": "kick", "untimeout": "untimeout", "reinvite": "reinvite", "link": "links"}
        from .service import LINK_ALIASES
        options = []
        for key, (name, desc) in COMMAND_DEFAULTS.items():
            need = "links" if key in LINK_ALIASES else required.get(key)
            if need and need not in features:
                continue
            options.append(discord.SelectOption(label="/" + name, value=key, description=desc[:100]))
        super().__init__(placeholder="Befehl zum Bearbeiten auswählen …", options=options)

    async def callback(self, interaction):
        view, key = self.view, self.values[0]
        c = command_options(view.client.service.settings(interaction.guild_id), key)
        async def submit(current, values):
            ids = []
            if values["channels"].casefold() not in {"", "alle"}:
                for raw in re.split(r"[,;\s]+", values["channels"]):
                    if raw:
                        ids.append((await get_destination(view.client, current.guild, raw, allow_forum=True)).id)
            visibility = values["visibility"].casefold()
            if visibility not in {"privat", "öffentlich", "oeffentlich"}:
                raise ValueError("Sichtbarkeit: privat oder öffentlich verwenden.")
            apply_settings(view.client.service, current.guild_id, {"command_settings": {key: {
                "name": values["name"], "description": values["description"], "ephemeral": visibility == "privat",
                "allowed_channel_ids": ids, "enabled": boolean(values["enabled"]),
            }}})
            from .slash_commands import refresh_commands
            try:
                await refresh_commands(view.client, current.guild_id)
            except discord.HTTPException:
                return "Gespeichert. Discord konnte die Befehlsliste gerade nicht aktualisieren; Name und Beschreibung werden beim nächsten Bot-Start synchronisiert."
            return f"**/{values['name']}** wurde gespeichert und mit Discord synchronisiert.\nDie Discord-Befehlsliste kann einen Moment brauchen, bis die Änderung sichtbar wird."
        await interaction.response.send_modal(Form(view.client, view.user_id, "Befehl /" + c["name"], [
            ("name", "Befehlsname (ohne /, nur klein)", c["name"], None, True),
            ("description", "Erklärung in der Befehlsliste (max. 100)", c["description"], None, True),
            ("visibility", "Antwort sichtbar: privat / öffentlich", "privat" if c["ephemeral"] else "öffentlich", None, True),
            ("channels", "Erlaubte Kanal-IDs, Komma; leer = alle", ",".join(str(x) for x in c["allowed_channel_ids"]), None, False),
            ("enabled", "Befehl aktiviert? ja / nein", "ja" if c["enabled"] else "nein", None, True),
        ], submit))


class CommandView(ManagedView):
    def __init__(self, client, user_id):
        super().__init__(client, user_id)
        self.add_item(CommandSelect(client))
        self.add_item(BackButton())


class OptionsView(ManagedView):
    def __init__(self, client, user_id, category):
        super().__init__(client, user_id)
        self.category = category
        self.add_item(BackButton())
        if category != "history":
            self.remove_item(self.scan_category)

    @discord.ui.button(label="Einstellungen bearbeiten", emoji="✏️", row=0)
    async def edit(self, interaction, button):
        c = self.client.service.settings(interaction.guild_id)
        definitions = {
            "birthdays": [("birthday_time", "Uhrzeit (24 Stunden, HH:MM)", c["birthday_time"], "00:00", True),
                          ("timezone", "Zeitzone", c["timezone"], "Europe/Vienna", True),
                          ("leap_day", "29. Februar: 28.02. / 01.03. / Schaltjahre", {"feb28":"28.02.","mar1":"01.03.","only_leap_years":"Schaltjahre"}[c["leap_day"]], None, True)],
            "activity": [("text_xp", "XP pro Textnachricht (0 = keine)", c["text_xp"], "15", True),
                         ("minimum_message_length", "Mindestlänge der Textnachricht", c["minimum_message_length"], "5", True),
                         ("voice_enabled", "Sprachchat-XP aktiviert? ja / nein", "ja" if c["voice_enabled"] else "nein", None, True),
                         ("voice_xp_per_minute", "XP pro Sprachchat-Minute", c["voice_xp_per_minute"], "10", True),
                         ("voice_message_xp_per_minute", "XP pro Sprachnachrichten-Minute", c.get("voice_message_xp_per_minute",10), "10", True)],
            "history": [("history_scan_limit", "Scan pro Kategorie: Zahl / alle / keine", c.get("history_scan_limit",50), "50", True),
                        ("log_message_content", "Nachrichteninhalte protokollieren? ja / nein", "ja" if c["log_message_content"] else "nein", None, True)],
            "appearance": [("color", "Akzentfarbe als #RRGGBB", c["color"], "#38bdf8", True),
                           ("welcome", "Willkommenstext", c.get("messages",{}).get("welcome", ""), "Willkommen {name} auf {server}!", False),
                           ("farewell", "Abschiedstext", c.get("messages",{}).get("farewell", ""), "{name} hat den Server verlassen.", False),
                           ("birthday", "Geburtstagsgruß", c.get("messages",{}).get("birthday", ""), "Alles Gute zum Geburtstag, {name}!", False)],
        }
        async def submit(current, values):
            patch = {}
            for key, value in values.items():
                if key in {"welcome","farewell","birthday"}:
                    patch.setdefault("messages",{})[key] = value
                elif key in {"voice_enabled","log_message_content"}:
                    patch[key] = boolean(value)
                elif key == "history_scan_limit":
                    patch[key] = scan_limit(value)
                elif key == "leap_day":
                    mapping = {"28.02.":"feb28","28.02":"feb28","01.03.":"mar1","01.03":"mar1","schaltjahre":"only_leap_years"}
                    if value.casefold() not in mapping:
                        raise ValueError("Für den 29. Februar: 28.02., 01.03. oder Schaltjahre eingeben.")
                    patch[key] = mapping[value.casefold()]
                elif SCHEMA.get(key,{}).get("type") == "integer":
                    patch[key] = integer(value, SCHEMA[key]["label"])
                else:
                    patch[key] = value
            apply_settings(self.client.service, current.guild_id, patch)
            return "Die Einstellungen wurden dauerhaft gespeichert. Änderungen am Startscan gelten beim nächsten Start oder manuellen Scan im Dashboard."
        await interaction.response.send_modal(Form(self.client,self.user_id,"Einstellungen bearbeiten",definitions[self.category],submit))

    @discord.ui.button(label="Scan für einzelne Kategorie", emoji="🔎", row=1)
    async def scan_category(self, interaction, button):
        async def submit(current, values):
            key = values["category"].lstrip("/")
            key = next((internal for internal,(name,_) in COMMAND_DEFAULTS.items() if name == key),key)
            labels = {"willkommen":"welcome","abschied":"farewell","geburtstage":"birthdays","allgemeine logs":"logs","streams":"youtube_streams"}
            key = labels.get(key.casefold(),key)
            apply_settings(self.client.service,current.guild_id,{"history_scan_overrides":{key:scan_limit(values["count"])}})
            return f"Die Kategorie **{key}** verwendet künftig **{values['count']}** Nachrichten beim Startscan. Bereits gespeicherte Verweise bleiben bestehen."
        await interaction.response.send_modal(Form(self.client,self.user_id,"Scan-Anzahl je Kategorie",[
            ("category","Kategorie oder Befehl ohne /",None,"logs, moderation, willkommen, rang, youtube …",True),
            ("count","Anzahl / alle / keine",50,None,True)],submit))


async def show_settings(client, interaction):
    if not await require_manager(client, interaction):
        return
    await interaction.response.send_message(embed=summary(client, interaction.guild_id), view=MainView(client, interaction.user.id), ephemeral=True)


def birthday_card(client, interaction):
    service = client.service
    c = service.settings(interaction.guild_id)
    value = service.store.birthday(interaction.guild_id, interaction.user.id)
    destination = c["channels"].get("birthdays")
    text = f"**Dein gespeichertes Datum:** {f'{value[0]:02}.{value[1]:02}.' if value else 'noch nicht eingetragen'}\n\n"
    text += "**So trägst du dich ein:** Klicke unten auf **Geburtstag eintragen / ändern** und gib Tag und Monat ein, zum Beispiel **27.05.**\n\n"
    text += f"**Wann erscheint der Gruß?** An deinem Geburtstag um **{c['birthday_time']} Uhr** in **{c['timezone']}**. "
    text += f"Der Gruß erscheint öffentlich in <#{destination}>." if destination else "Ein Zielkanal fehlt noch; die Verwaltung muss ihn zuerst einstellen."
    text += "\n\nDein Geburtsjahr und Alter werden nicht gespeichert. Mit dem Eintragen erlaubst du den öffentlichen Glückwunsch. Dein Eintrag lässt sich hier jederzeit löschen."
    return card(client, interaction.guild_id, "🎂 Dein Geburtstag", text)


class BirthdayModal(discord.ui.Modal, title="Deinen Geburtstag eintragen"):
    date = discord.ui.TextInput(label="Tag und Monat (ohne Geburtsjahr)", placeholder="27.05.", max_length=6)

    def __init__(self, client, user_id):
        super().__init__(timeout=600)
        self.client, self.user_id = client,user_id

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id or not interaction.guild:
            await interaction.response.send_message("Bitte dein eigenes Geburtstagsformular öffnen.",ephemeral=True)
            return
        try:
            self.client.service.birthday(self.client.actor(interaction.user),[self.date.value],"/")
            await interaction.response.send_message(embed=birthday_card(self.client,interaction),view=BirthdayView(self.client,self.user_id),ephemeral=True)
        except ValueError as exc:
            await interaction.response.send_message("⚠️ "+str(exc),ephemeral=True)


class BirthdayView(discord.ui.View):
    def __init__(self,client,user_id):
        super().__init__(timeout=900)
        self.client,self.user_id=client,user_id

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.user_id:
            await interaction.response.send_message("Bitte mit /geburtstag dein eigenes Menü öffnen.",ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Geburtstag eintragen / ändern",emoji="🎂",style=discord.ButtonStyle.primary)
    async def set_date(self,interaction,button):
        await interaction.response.send_modal(BirthdayModal(self.client,self.user_id))

    @discord.ui.button(label="Meinen Eintrag löschen",emoji="🗑️",style=discord.ButtonStyle.secondary)
    async def delete_date(self,interaction,button):
        self.client.service.store.delete_birthday(interaction.guild_id,self.user_id)
        await interaction.response.edit_message(embed=birthday_card(self.client,interaction),view=self)


async def show_birthday(client,interaction):
    await interaction.response.send_message(embed=birthday_card(client,interaction),view=BirthdayView(client,interaction.user.id),ephemeral=True)
