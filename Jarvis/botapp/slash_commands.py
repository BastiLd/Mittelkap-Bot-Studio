from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Literal

import discord
from discord import app_commands

from .service import LINK_ALIASES, SLASH_NAMES
from .settings_schema import OWNER_ID, COMMAND_DEFAULTS, command_options
from .settings_ui import show_settings, show_birthday, BirthdayModal


class InteractionChannel:
    """Plain deferred command responses; figure assets are currently disabled."""

    def __init__(self, interaction, client=None, category=None, ephemeral=False):
        self.interaction = interaction
        self.client = client
        self.category = category
        self.ephemeral = ephemeral
        self.id = interaction.channel_id
        self.finished = False

    async def send(self, *args, **kwargs):
        kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
        # A downstream sender must never turn a private command response public.
        kwargs["ephemeral"] = self.ephemeral or kwargs.get("ephemeral", False)
        result = await self.interaction.followup.send(*args, **kwargs, wait=True)
        self.finished = True
        index = getattr(self.client, "index", None)
        if index and not kwargs["ephemeral"] and isinstance(result, discord.Message):
            index.record(result, self.category or "command")
        return result

    async def failure(self):
        try:
            await self.send(embed=discord.Embed(title="Anfrage nicht abgeschlossen",
                description="Bitte Eingaben, Berechtigungen und die Bot-Protokolle prüfen.", color=0xEAB45E))
        except discord.HTTPException as exc:
            logging.getLogger(__name__).warning("Fehlerhinweis nicht zustellbar (%s).", type(exc).__name__)


def access_reason(client, interaction, command):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return "Dieser Befehl funktioniert nur auf dem Server."
    if interaction.user.id == OWNER_ID:
        return None
    options = command_options(client.service.settings(interaction.guild_id), command)
    if not options["enabled"]:
        return "⏸️ Dieser Befehl ist derzeit deaktiviert. Die Serververwaltung kann ihn unter /einstellungen wieder aktivieren."
    allowed = {int(v) for v in options["allowed_channel_ids"]}
    parent = getattr(getattr(interaction, "channel", None), "parent_id", None)
    if allowed and interaction.channel_id not in allowed and parent not in allowed:
        return "📍 Dieser Befehl ist nur in diesen Kanälen erlaubt: " + ", ".join(f"<#{v}>" for v in sorted(allowed))
    return None


async def invoke(client, interaction: discord.Interaction, command: str, args: list[str], *, acknowledged=False, response_private=None, moderation_options=None):
    reason = access_reason(client, interaction, command)
    if reason:
        sender = interaction.followup.send if acknowledged else interaction.response.send_message
        await sender(reason, ephemeral=True)
        return
    options = command_options(client.service.settings(interaction.guild_id), command)
    private = (options["ephemeral"] if response_private is None else response_private) or command == "birthday"
    if not acknowledged:
        await interaction.response.defer(ephemeral=private, thinking=True)
    channel = InteractionChannel(interaction, client, command, private)
    message = SimpleNamespace(id=interaction.id, guild=interaction.guild, author=interaction.user,
                              channel=channel, content="/" + options["name"] + (" " + " ".join(args) if args else ""),
                              interaction=interaction, jump_url=f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}", moderation_options=moderation_options or {})
    try:
        await client.dispatch_command(message, (command, args))
    except Exception as exc:
        logging.getLogger(__name__).error("Slash-Befehl fehlgeschlagen (%s).", type(exc).__name__)
        await channel.failure()
    finally:
        if not channel.finished:
            await channel.failure()


def make_tree(client, tree=None, guild_id=None) -> app_commands.CommandTree:
    tree = tree or app_commands.CommandTree(client)
    tree.clear_commands(guild=None)
    base = client.service.config.base
    if guild_id is None:
        row = client.service.store.db.execute("SELECT guild FROM settings ORDER BY guild LIMIT 1").fetchone()
        guild_id = row[0] if row else None
    settings = client.service.settings(guild_id) if guild_id is not None else base
    features = set(base["features"]) | set(settings["features"])
    for override in base.get("guilds", {}).values():
        features.update(override.get("features", []))

    def add(names, description, callback):
        name = names[0]
        internal = next((k for k,(public,_) in COMMAND_DEFAULTS.items() if public == name), name)
        options = command_options(settings, internal)
        command = app_commands.Command(name=options["name"], description=options["description"], callback=callback)
        command.guild_only = True
        async def permitted(interaction):
            reason = access_reason(client, interaction, internal)
            if reason:
                raise app_commands.CheckFailure(reason)
            return True
        command.add_check(permitted)
        tree.add_command(command)

    def simple(command):
        async def callback(interaction: discord.Interaction):
            await invoke(client, interaction, command, [])
        return callback

    add(("hilfe",), "Alle Befehle und ihre Aufgaben anzeigen", simple("help"))
    add(("status",), "Prüfen, ob der Bot erreichbar ist", simple("ping"))
    if "links" in features:
        for platform, aliases in LINK_ALIASES.items():
            add((platform,), f"Das {platform.title()}-Profil von Mittelkap anzeigen", simple(platform))

    if "rank" in features:
        @app_commands.describe(mitglied="Wessen Rangkarte? Leer lassen, um deine eigene Aktivität zu sehen.")
        async def rank(interaction: discord.Interaction, mitglied: discord.Member | None = None):
            await invoke(client, interaction, "rank", [f"<@{mitglied.id}>"] if mitglied else [])
        add(("rang",), "Deine Serveraktivität als Rangkarte anzeigen", rank)

    if "birthdays" in features:
        @app_commands.describe(aktion="Anzeigen öffnet dein persönliches Menü; setzen speichert dein Datum; löschen entfernt es.", datum="Nur Tag und Monat, zum Beispiel 27.05. – ohne Geburtsjahr.")
        async def birthday(interaction: discord.Interaction, aktion: Literal["anzeigen", "setzen", "löschen"] = "anzeigen", datum: str | None = None):
            reason = access_reason(client, interaction, "birthday")
            if reason:
                await interaction.response.send_message(reason, ephemeral=True)
                return
            if aktion == "anzeigen" and not datum:
                await show_birthday(client, interaction)
                return
            if aktion == "setzen" and not datum:
                await interaction.response.send_modal(BirthdayModal(client, interaction.user.id))
                return
            args = [datum] if datum and aktion != "löschen" else ["löschen"]
            await invoke(client, interaction, "birthday", args)
        add(("geburtstag",), "Deinen Geburtstag ohne Geburtsjahr verwalten", birthday)

        @app_commands.describe(mitglied="Mitglied mit freiwillig eingetragenem Geburtstag", text="Dein Gruß (maximal 500 Zeichen); erscheint im Geburtstagskanal.")
        async def congratulate(interaction: discord.Interaction, mitglied: discord.Member, text: str | None = None):
            await invoke(client, interaction, "congratulate", [str(mitglied.id)] + ([text] if text else []))
        add(("gratuliere",), "Einem eingetragenen Mitglied einen Geburtstagsgruß senden", congratulate)

    async def setup(interaction: discord.Interaction):
        await show_settings(client, interaction)
    add(("einstellungen",), "Verständliche Verwaltung für diesen Server öffnen", setup)

    if "links" in features:
        @app_commands.describe(plattform="Welches Profil möchtest du verknüpfen?", adresse="Vollständiger https://-Profillink; aus entfernt den Eintrag.")
        async def link(interaction: discord.Interaction, plattform: Literal["youtube", "twitch", "tiktok", "instagram", "twitter", "facebook", "discord", "playstation", "xbox", "nintendo", "linktree"], adresse: str):
            await invoke(client, interaction, "link", [plattform, adresse])
        add(("profillink",), "Einen Profillink hinterlegen; adresse aus entfernt ihn", link)

    if "notifications" in features:
        @app_commands.describe(plattform="Plattform des Creators", konto="Profil-Link, Nutzername oder YouTube-UC-Kanal-ID; leer zeigt deine Quellen.",
                               aktion="Hinzufügen richtet automatische Meldungen ein; entfernen beendet sie.", livestreams="Bei YouTube auch Livestreams melden (benötigt YouTube-API-Schlüssel).")
        async def source(interaction: discord.Interaction, plattform: Literal["youtube", "twitch", "tiktok"], konto: str | None = None,
                         aktion: Literal["hinzufügen", "entfernen"] = "hinzufügen", livestreams: bool = False):
            reason = access_reason(client, interaction, "quelle")
            if reason:
                await interaction.response.send_message(reason, ephemeral=True)
                return
            if not konto:
                await invoke(client, interaction, "quelle", [])
                return
            from .settings_ui import require_manager
            if not await require_manager(client, interaction):
                return
            options = command_options(client.service.settings(interaction.guild_id), "quelle")
            await interaction.response.defer(ephemeral=options["ephemeral"], thinking=True)
            try:
                from .notifications import resolve_source_account
                account = await resolve_source_account(client.session, plattform, konto)
            except Exception as exc:
                # Platform details may contain response data; only expected input errors reach the user.
                text = str(exc) if isinstance(exc, ValueError) else "Das Profil konnte gerade nicht gelesen werden. Bitte Konto/Link prüfen und erneut versuchen."
                await interaction.followup.send("⚠️ " + text, ephemeral=options["ephemeral"])
                return
            args = (["entfernen", plattform, account] if aktion == "entfernen" else
                    [plattform, account] + (["live"] if livestreams and plattform == "youtube" else []))
            await invoke(client, interaction, "quelle", args, acknowledged=True, response_private=options["ephemeral"])
        add(("quelle",), "Quellen für neue Inhalte verwalten (nur Verwaltung)", source)

    if "activity" in features:
        @app_commands.describe(stufe="Ab dieser Stufe wird die Rolle zusätzlich vergeben.", rolle="Unprivilegierte Rolle unter der Bot-Rolle wählen.", entfernen="Ja entfernt die Belohnungsrolle für diese Stufe.")
        async def role(interaction: discord.Interaction, stufe: app_commands.Range[int, 0], rolle: discord.Role | None = None, entfernen: bool = False):
            if not rolle and not entfernen:
                await interaction.response.send_message("Bitte eine Rolle auswählen oder entfernen auf wahr setzen.", ephemeral=True)
                return
            await invoke(client, interaction, "rollen", [str(stufe), "aus" if entfernen else str(rolle.id)])
        add(("stufenrolle",), "Eine nicht privilegierte Belohnungsrolle für eine Stufe festlegen", role)

    if "timeout" in features:
        @app_commands.describe(mitglied="Mitglied, das vorübergehend nicht schreiben/sprechen darf.", dauer="Zum Beispiel 10m, 2h oder 1d; mindestens 1 Sekunde, höchstens 28 Tage.", grund="Nachvollziehbare Begründung für das Moderationsprotokoll.")
        async def timeout(interaction: discord.Interaction, mitglied: discord.Member, dauer: str, grund: str | None = None):
            await invoke(client, interaction, "timeout", [str(mitglied.id), dauer] + ([grund] if grund else []))
        add(("stummschalten",), "Ein Mitglied mit Moderatorrechten vorübergehend stummschalten", timeout)

    if "ban" in features:
        @app_commands.describe(mitglied="Mitglied, das vom Server ausgeschlossen werden soll.", grund="Begründung, die im Moderationsprotokoll erscheint.")
        async def ban(interaction: discord.Interaction, mitglied: discord.Member, grund: str | None = None):
            await invoke(client, interaction, "ban", [str(mitglied.id)] + ([grund] if grund else []))
        add(("bannen",), "Ein Mitglied mit passenden Moderationsrechten bannen", ban)

    if "kick" in features:
        @app_commands.describe(mitglied="Mitglied, das den Server verlassen muss.", grund="Nachvollziehbarer Grund für das Protokoll.")
        async def kick(interaction: discord.Interaction, mitglied: discord.Member, grund: str):
            await invoke(client, interaction, "kick", [str(mitglied.id), grund])
        add(("kicken",), "Ein Mitglied entfernen; eine Rückkehr braucht eine neue Einladung", kick)

    if "untimeout" in features:
        @app_commands.describe(mitglied="Mitglied, dessen Timeout aufgehoben wird.", grund="Warum darf die Person wieder schreiben und sprechen?")
        async def untimeout(interaction: discord.Interaction, mitglied: discord.Member, grund: str):
            await invoke(client, interaction, "untimeout", [str(mitglied.id), grund])
        add(("stummschaltungaufheben",), "Einen laufenden Timeout aufheben", untimeout)

    if "unban" in features:
        @app_commands.describe(nutzer_id="Discord-Nutzer-ID der gesperrten Person.", grund="Begründung für Protokoll und optionale Privatnachricht.", privatnachricht="Nach erfolgreichem Entbannen eine private Einladung schicken?", kanal="Textkanal für die Einladung; bei Privatnachricht erforderlich.")
        async def unban(interaction: discord.Interaction, nutzer_id: str, grund: str | None = None, privatnachricht: bool = False, kanal: discord.TextChannel | None = None):
            await invoke(client, interaction, "unban", [nutzer_id] + ([grund] if grund else []), moderation_options={"notify":privatnachricht,"invite_channel":kanal.id if kanal else None})
        add(("entbannen",), "Eine Serversperre aufheben; optional eine private Einladung senden", unban)

    if "reinvite" in features:
        @app_commands.describe(nutzer_id="Discord-Nutzer-ID der Person nach Kick oder Entbannung.", kanal="Textkanal dieses Servers; der Bot braucht dort Einladung erstellen.", grund="Freier Text für Einladung und Moderationsprotokoll.", privatnachricht="Einladung direkt privat senden; bei aus erhältst nur du den Link.")
        async def reinvite(interaction: discord.Interaction, nutzer_id: str, kanal: discord.TextChannel, grund: str, privatnachricht: bool = False):
            await invoke(client, interaction, "reinvite", [nutzer_id, grund], moderation_options={"notify":privatnachricht,"invite_channel":kanal.id})
        add(("einladen",), "Eine Einladung nach Kick oder Entbannung erstellen; optional privat senden", reinvite)

    @tree.error
    async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        text = str(error) if isinstance(error, app_commands.CheckFailure) else "Der Befehl konnte nicht abgeschlossen werden. Bitte Eingaben, Berechtigungen und die Bot-Protokolle prüfen."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        import logging
        logging.getLogger(__name__).error("Slash-Befehl fehlgeschlagen (%s).", type(error).__name__)

    return tree


async def refresh_commands(client, guild_id=None):
    """Reuse the existing tree; Discord clients may only own one CommandTree."""
    make_tree(client, client.tree, guild_id)
    synced = await client.tree.sync()
    return [command.name for command in synced]
