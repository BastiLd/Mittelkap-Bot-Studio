from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import aiohttp
import discord

from .service import Reply

MOD_COMMANDS = {"ban", "unban", "timeout", "kick", "untimeout", "reinvite"}
HARMFUL = {"ban", "timeout", "kick"}
ACTION_LABELS = {"timeout": "Timeout vergeben", "ban": "Mitglied gebannt", "unban": "Mitglied entbannt", "kick": "Mitglied gekickt", "untimeout": "Timeout aufgehoben", "reinvite": "Einladung erstellt"}
OWNER_ID = 965593518745731152


def user_id(value: str) -> int:
    match = re.fullmatch(r"(?:<@!?(\d{1,20})>|(\d{1,20}))", value)
    if not match or not 0 < int(match.group(1) or match.group(2)) < 2**64:
        raise ValueError("Bitte ein Mitglied erwähnen oder eine gültige Nutzer-ID angeben.")
    return int(match.group(1) or match.group(2))


def duration_seconds(value: str) -> int:
    parts = re.findall(r"(\d+)([smhd])", value.casefold())
    if not parts or "".join(n + unit for n, unit in parts) != value.casefold():
        raise ValueError("Dauer mit s, m, h oder d angeben, zum Beispiel 10m, 2h oder 1h30m.")
    seconds = sum(int(n) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] for n, unit in parts)
    if not 1 <= seconds <= 28 * 86400:
        raise ValueError("Ein Timeout muss zwischen einer Sekunde und 28 Tagen liegen.")
    return seconds


class Moderation:
    def __init__(self, service, client=None):
        self.service = service
        self.client = client
        self.lock = asyncio.Lock()
        self.service.store.db.execute("""CREATE TABLE IF NOT EXISTS moderation_targets (
            guild INTEGER NOT NULL, user INTEGER NOT NULL, name TEXT NOT NULL,
            last_action TEXT NOT NULL, reason TEXT NOT NULL, updated TEXT NOT NULL,
            banned INTEGER, kicked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild,user))""")
        self.service.store.db.commit()
        if not service.store.state(0,"moderation_targets_v1"):
            for row in service.store.db.execute("SELECT * FROM moderation WHERE status='succeeded' ORDER BY id").fetchall():
                meta = json.loads(row["metadata"] or "{}")
                self.remember(row["guild"], row["target"], row["action"], row["reason"], name=meta.get("target_name"), created=row["created"])
            service.store.set_state(0,"moderation_targets_v1","1")

    def remember(self, guild, user, action, reason="", *, name=None, created=None):
        uid = getattr(user, "id", user)
        display = name or getattr(user, "display_name", None) or str(user)
        previous = self.service.store.db.execute("SELECT * FROM moderation_targets WHERE guild=? AND user=?", (guild, uid)).fetchone()
        if action == "join" and previous is None:
            return
        banned = 1 if action == "ban" else (0 if action in {"unban", "kick", "join"} else previous["banned"] if previous else None)
        kicked = 1 if action == "kick" else (0 if action == "join" else previous["kicked"] if previous else 0)
        with self.service.store.db:
            self.service.store.db.execute("INSERT OR REPLACE INTO moderation_targets VALUES (?,?,?,?,?,?,?,?)",
                (guild, uid, display, action, reason, created or datetime.now(timezone.utc).isoformat(), banned, kicked))

    def target_history(self, guild):
        return [dict(r) for r in self.service.store.db.execute("SELECT * FROM moderation_targets WHERE guild=? ORDER BY updated DESC", (guild,))]

    def update_metadata(self, audit_id, metadata):
        with self.service.store.db:
            self.service.store.db.execute("UPDATE moderation SET metadata=? WHERE id=?", (json.dumps(metadata), audit_id))

    @staticmethod
    def result(reply, status, notification="not_requested", **details):
        reply.moderation_result = {"moderation_status": status, "notification_status": notification, **details}
        return reply

    async def execute(self, message, command: str, args: list[str]) -> Reply:
        guild = message.guild
        c = self.service.settings(guild.id)
        if command not in c["features"]:
            return Reply("Aufgabenverteilung", "Diese Moderationsaktion gehört nicht zu meinen aktivierten Aufgaben.")
        if len(args) < (2 if command == "timeout" else 1):
            return Reply("Eingabe prüfen", "Ziel und Grund angeben. /stummschalten braucht zusätzlich eine Dauer; /einladen einen Textkanal für die Einladung. Alle Beispiele stehen in /hilfe.")
        try:
            target_id = user_id(args[0])
            if target_id == OWNER_ID and command in HARMFUL:
                return Reply("Geschütztes Mitglied", "Basti ist als oberster Bot-Verwalter dauerhaft vor Bann, Kick und Timeout geschützt.")
            seconds = duration_seconds(args[1]) if command == "timeout" else None
            reason = " ".join(args[2:] if command == "timeout" else args[1:]) or "Kein Grund angegeben"
            if len(reason) > 350:
                raise ValueError("Der Grund darf höchstens 350 Zeichen enthalten.")
        except ValueError as exc:
            return Reply("Eingabe prüfen", str(exc))
        options = getattr(message, "moderation_options", {})
        notify = options.get("notify", False)
        if type(notify) is not bool:
            return Reply("Eingabe prüfen", "Privatnachricht muss an oder aus sein.")
        if notify and command not in {"unban", "reinvite"}:
            return Reply("Eingabe prüfen", "Private Einladungen sind nur beim Entbannen oder Einladen vorgesehen.")
        needs_invite = command == "reinvite" or (command == "unban" and notify)
        if needs_invite and "reinvite" not in c["features"]:
            return Reply("Aufgabenverteilung", "Einladungen sind bei diesem Bot deaktiviert. Entbannen ist weiterhin ohne optionale Privatnachricht möglich.")
        invite_channel = None
        # Native Discord permissions are required independently of configuration-management roles.
        permission = {"timeout": "moderate_members", "untimeout": "moderate_members", "kick": "kick_members", "reinvite": "ban_members"}.get(command, "ban_members")
        try:
            # Refresh both issuer and bot permissions; do not trust an old member cache for sanctions.
            actor = await guild.fetch_member(message.author.id)
            bot = await guild.fetch_member(guild.me.id)
            if (actor.id != OWNER_ID and not getattr(actor.guild_permissions, permission, False)) or not getattr(bot.guild_permissions, permission, False):
                return Reply("Keine Berechtigung", "Dir oder mir fehlt die erforderliche Discord-Berechtigung (Mitglieder moderieren, kicken oder bannen). Zum sicheren Prüfen einer Wieder-Einladung braucht der Bot Bannrechte.")
            required_roles = {int(r) for r in c.get("moderator_role_ids", []) + c.get("admin_role_ids", [])}
            if required_roles and actor.id not in {guild.owner_id, OWNER_ID} and not required_roles.intersection(r.id for r in actor.roles):
                return Reply("Keine Berechtigung", "Zusätzlich ist eine ausdrücklich konfigurierte Moderationsrolle erforderlich.")
            if command in HARMFUL and target_id in {actor.id, bot.id, guild.owner_id}:
                return Reply("Geschütztes Mitglied", "Diese Aktion ist gegen dich selbst, mich oder den Serverinhaber nicht zulässig.")
            if command == "unban":
                target = (await guild.fetch_ban(discord.Object(id=target_id))).user
            elif command == "reinvite":
                try:
                    await guild.fetch_ban(discord.Object(id=target_id))
                except discord.NotFound:
                    pass
                else:
                    return Reply("Zuerst entbannen", "Diese Person ist noch gebannt. Erst ausdrücklich entbannen; eine Einladung allein hebt keinen Bann auf.")
                if self.client is None:
                    return Reply("Ziel nicht erreichbar", "Für die Einladung wird die aktive Discord-Anbindung benötigt.")
                target = await self.client.fetch_user(target_id)
            else:
                target = await guild.fetch_member(target_id)
                if target.top_role >= bot.top_role or (actor.id not in {guild.owner_id, OWNER_ID} and target.top_role >= actor.top_role):
                    return Reply("Rollenhierarchie", "Die höchste Zielrolle muss unter deiner und meiner höchsten Rolle liegen.")
                if command in HARMFUL and {int(r) for r in c.get("protected_role_ids", [])}.intersection(r.id for r in target.roles):
                    return Reply("Geschütztes Mitglied", "Dieses Mitglied hat eine geschützte Rolle.")
                if command == "timeout" and (target.bot or target.guild_permissions.administrator):
                    return Reply("Geschütztes Mitglied", "Bots und Administratoren erhalten keinen Timeout.")
            if needs_invite:
                selected = options.get("invite_channel")
                if not selected or not str(selected).isdigit():
                    return Reply("Einladungskanal fehlt", "Bitte einen Textkanal auswählen, über den die Person wieder beitreten darf.")
                getter = getattr(guild, "get_channel_or_thread", guild.get_channel)
                invite_channel = getter(int(selected)) or await guild.fetch_channel(int(selected))
                if not isinstance(invite_channel, discord.TextChannel) or invite_channel.guild.id != guild.id:
                    return Reply("Einladungskanal prüfen", "Einladungen benötigen einen Textkanal dieses Servers; ein Forum oder Beitrag ist dafür nicht geeignet.")
                bp, ap = invite_channel.permissions_for(bot), invite_channel.permissions_for(actor)
                if not (bp.view_channel and getattr(bp, "create_instant_invite", False)) or (actor.id != OWNER_ID and not (ap.view_channel and getattr(ap, "create_instant_invite", False))):
                    return Reply("Keine Einladungsrechte", "Dir oder mir fehlt im ausgewählten Kanal „Einladung erstellen“ oder „Kanal ansehen“.")
            channel_id = int(c["channels"].get("moderation") or c["channels"].get("logs") or 0)
            getter = getattr(guild, "get_channel_or_thread", guild.get_channel)
            channel = getter(channel_id)
            if channel is None and channel_id and hasattr(guild, "fetch_channel"):
                channel = await guild.fetch_channel(channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return Reply("Protokollkanal fehlt", "Bitte zuerst in /einstellungen → Zielkanäle einen Textkanal oder Forum-Beitrag für Moderation auswählen.")
            perms = channel.permissions_for(bot)
            can_send = getattr(perms, "send_messages_in_threads", False) if isinstance(channel, discord.Thread) else perms.send_messages
            if not (perms.view_channel and can_send and perms.embed_links):
                return Reply("Protokollkanal prüfen", "Im Moderationskanal fehlen mir Lese-, Schreib- oder Embed-Rechte.")
        except discord.NotFound:
            return Reply("Ziel nicht gefunden", "Das Mitglied ist nicht auf dem Server oder die angegebene Nutzer-ID ist nicht gebannt.")
        except discord.HTTPException:
            return Reply("Prüfung fehlgeschlagen", "Discord konnte die aktuellen Rechte oder das Ziel nicht bestätigen. Es wurde keine Aktion ausgeführt.")
        async with self.lock:
            web_account = getattr(message, "dashboard_account", None)
            if web_account:
                # Recheck revocation after Discord member/role lookups and lock waiting.
                message.dashboard_authorize()
            source_id = getattr(message.channel, "id", None)
            metadata = {"actor_name": str(actor), "target_name": str(target), "source_channel": source_id,
                        "source_url": getattr(message, "jump_url", f"https://discord.com/channels/{guild.id}/{source_id}"),
                        "command": getattr(message, "content", f"/{command}"), "invocation": "dashboard" if getattr(message, "content", "").startswith("Dashboard:") else ("slash" if getattr(message, "interaction", None) else "message")}
            if web_account:
                metadata["dashboard_account"] = {key: str(web_account[key]) for key in ("id", "username", "display_name")}
            metadata.update(notification_status="pending" if notify else "not_requested", invite_channel=options.get("invite_channel"))
            audit, fresh = self.service.store.reserve_moderation(guild.id, message.id, actor.id, target_id, command, seconds, reason, metadata)
            if not fresh:
                return self.result(Reply("Bereits bearbeitet", f"Dieser Befehl ist unter Vorgang #{audit['id']} bereits erfasst (Status: {audit['status']}). Er wird nicht erneut ausgeführt."), audit["status"], json.loads(audit["metadata"]).get("notification_status", "not_requested"), audit_id=audit["id"])
            attribution = (f"Webkonto {web_account['username']} ({web_account['id']})" if web_account else f"Moderator {actor.id}")
            audit_reason = f"{c['name']} | {attribution} | Vorgang {audit['id']} | {reason}"[:512]
            invite = None
            try:
                if command == "timeout":
                    await target.timeout(timedelta(seconds=seconds), reason=audit_reason)
                elif command == "untimeout":
                    await target.timeout(None, reason=audit_reason)
                elif command == "kick":
                    await guild.kick(target, reason=audit_reason)
                elif command == "reinvite":
                    invite = await invite_channel.create_invite(max_age=86400, max_uses=1, unique=True, reason=audit_reason)
                    metadata["invite_url"] = str(invite.url)
                    self.update_metadata(audit["id"], metadata)
                elif command == "ban":
                    await guild.ban(target, reason=audit_reason, delete_message_seconds=0)
                else:
                    await guild.unban(target, reason=audit_reason)
            except discord.Forbidden:
                self.service.store.finish_moderation(audit["id"], "failed", "Forbidden")
                return self.result(Reply("Aktion abgelehnt", "Discord hat die Aktion abgelehnt. Bitte Botrechte und Rollen prüfen."), "failed", audit_id=audit["id"])
            except discord.NotFound:
                self.service.store.finish_moderation(audit["id"], "failed", "NotFound")
                return self.result(Reply("Ziel nicht gefunden", "Das Ziel ist nicht mehr verfügbar. Die Aktion wurde nicht ausgeführt."), "failed", audit_id=audit["id"])
            except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
                self.service.store.finish_moderation(audit["id"], "unknown", "TransportError")
                return self.result(Reply("Ergebnis unklar", f"Die Antwort von Discord fehlt. Vorgang #{audit['id']} wurde protokolliert. Bitte den tatsächlichen Serverzustand prüfen, bevor du den Befehl erneut schickst."), "unknown", audit_id=audit["id"])
            self.service.store.finish_moderation(audit["id"], "succeeded")
            self.remember(guild.id, target, command, reason)
            if notify and command in {"unban", "reinvite"}:
                # A failed or revoked optional DM never rolls back a completed unban.
                try:
                    if web_account:
                        message.dashboard_authorize()
                    if invite is None:
                        invite = await invite_channel.create_invite(max_age=86400, max_uses=1, unique=True, reason=audit_reason)
                        metadata["invite_url"] = str(invite.url)
                        self.update_metadata(audit["id"], metadata)
                    if web_account:
                        message.dashboard_authorize()
                    embed = discord.Embed(title="Einladung zurück auf den Server", description=f"**{discord.utils.escape_markdown(guild.name)}** lädt dich wieder ein.\n\n**Nachricht der Moderation**\n{discord.utils.escape_markdown(reason)}\n\n[Server beitreten]({invite.url})", color=0x829bff)
                    embed.set_footer(text="Die Einladung gilt 24 Stunden und kann einmal verwendet werden. Der Beitritt ist freiwillig.")
                    await target.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    metadata["notification_status"] = "sent"
                except (discord.Forbidden, discord.NotFound):
                    metadata["notification_status"] = "failed"
                    metadata["notification_error"] = "Discord hat die Einladung oder Privatnachricht abgelehnt (zum Beispiel geschlossene DMs)."
                except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
                    metadata["notification_status"] = "unknown"
                    metadata["notification_error"] = "Keine eindeutige Discord-Antwort; keine automatische Wiederholung."
                except ValueError:
                    metadata["notification_status"] = "failed"
                    metadata["notification_error"] = "Webrechte wurden zwischenzeitlich entzogen; kein weiterer Versand."
                self.update_metadata(audit["id"], metadata)
        action = ACTION_LABELS[command]
        intro = self.service.style("Die Aktion wurde erfolgreich ausgeführt.", "Anweisung ausgeführt. Die Ordnung ist wiederhergestellt.")
        author_label = f"Webkonto: {web_account['display_name']} ({web_account['username']})" if web_account else f"Moderator: {actor.id}"
        reply = Reply(action, f"{intro}\nZiel: {target_id}\n{author_label}\nGrund: {reason}"
                     + (f"\nDauer: {seconds} Sekunden" if seconds else "") + f"\nVorgang: #{audit['id']}")
        if command == "kick":
            reply.text += "\nEin Kick lässt sich nicht rückgängig machen. Jarvis kann danach eine neue Einladung erstellen; die Person muss selbst beitreten."
        if metadata.get("invite_url"):
            reply.text += f"\nEinladung (24 Stunden, einmal nutzbar): {metadata['invite_url']}"
        if notify:
            reply.text += "\nPrivatnachricht: " + {"sent": "erfolgreich gesendet", "failed": "nicht zugestellt – die ausgeführte Moderationsaktion bleibt erfolgreich", "unknown": "Zustellung unklar – die ausgeführte Moderationsaktion bleibt erfolgreich"}.get(metadata["notification_status"], "nicht ausgeführt")
        return self.result(reply, "succeeded", metadata["notification_status"], audit_id=audit["id"], invite_url=metadata.get("invite_url"))

    def audit_reply(self, audit: dict) -> Reply:
        action = ACTION_LABELS.get(audit["action"], audit["action"])
        meta = json.loads(audit.get("metadata") or "{}")
        states = {"succeeded": "Erfolgreich ausgeführt", "failed": "Von Discord abgelehnt / fehlgeschlagen", "unknown": "Ergebnis unklar – Serverzustand prüfen", "pending": "Noch nicht abgeschlossen"}
        reply = Reply(f"Moderation #{audit['id']} · {action}", states.get(audit["status"], audit["status"]), timestamp=audit["created"])
        reply.fields = [
            ("Aktion", action, True), ("Status", audit["status"], True),
            ("Betroffenes Mitglied", f"{meta.get('target_name', 'Nicht im Cache')}\n[{audit['target']}](https://discord.com/users/{audit['target']})", False),
            ("Ausführender Moderator", f"{meta.get('actor_name', 'Nicht im Cache')}\n[{audit['actor']}](https://discord.com/users/{audit['actor']})", False),
            ("Grund", discord.utils.escape_markdown(audit["reason"]), False),
            ("Zeitpunkt (UTC)", audit["created"], False)]
        if meta.get("dashboard_account"):
            web_account = meta["dashboard_account"]
            reply.fields[3] = ("Auslösendes Webkonto", f"{web_account['display_name']} · `{web_account['username']}`\nKonto-ID: `{web_account['id']}`", False)
            reply.fields.insert(4, ("Delegierte Discord-Prüfung", f"Botrechte und Rollen wurden unter Controller <@{audit['actor']}> geprüft. Die Aktion wurde vom oben genannten Webkonto beauftragt.", False))
        if audit["duration"]:
            reply.fields.append(("Dauer", f"{audit['duration']} Sekunden ({audit['duration'] / 60:g} Minuten)", True))
        if meta.get("source_channel"):
            reply.fields.append(("Aufrufkanal", f"<#{meta['source_channel']}> · [Kanal öffnen]({meta['source_url']})", False))
        if meta.get("command"):
            reply.fields.append(("Aufruf", discord.utils.escape_markdown(meta["command"])[:800], False))
        reply.fields.append(("Nachverfolgung", f"Vorgang #{audit['id']} · {dict(slash='Interaktion', dashboard='Dashboard-Auftrag').get(meta.get('invocation'), 'Nachricht')} {audit['message']}", False))
        if meta.get("notification_status") and meta["notification_status"] != "not_requested":
            labels = {"sent": "Zugestellt", "failed": "Nicht zugestellt", "unknown": "Zustellung unklar", "pending": "Nicht abgeschlossen; keine automatische Wiederholung"}
            reply.fields.append(("Private Einladung", labels.get(meta["notification_status"], meta["notification_status"]) + ("\n" + meta["notification_error"] if meta.get("notification_error") else ""), False))
        if meta.get("invite_url"):
            reply.fields.append(("Einladung", f"[Server beitreten]({meta['invite_url']}) · 24 Stunden, einmal nutzbar", False))
        if audit["error"]:
            reply.fields.append(("Fehlerart", audit["error"], False))
        return reply
