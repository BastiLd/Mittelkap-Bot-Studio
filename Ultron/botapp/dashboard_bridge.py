"""Execute authenticated local dashboard requests inside the real bot event loop."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from io import BytesIO
from types import SimpleNamespace

import discord

from .control_bus import ControlBus, OWNER_ID

log = logging.getLogger(__name__)


class DashboardBridge:
    def __init__(self, client):
        self.client = client
        self.bus = None
        self.task = None
        self.heartbeat = None
        self.bot = client.service.config.base["persona"]

    async def start(self):
        self.bus = ControlBus()
        self.bus.recover(self.bot)
        self.task = asyncio.create_task(self.run(), name="dashboard-bridge")
        self.heartbeat = asyncio.create_task(self.beat(), name="dashboard-heartbeat")

    async def close(self):
        for task in (self.task, self.heartbeat):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self.bus:
            self.bus.publish(self.bot, {"online": False, "guilds": []})
            self.bus.close()
            self.bus = None

    async def run(self):
        await self.client.wait_until_ready()
        while not self.client.is_closed():
            try:
                action = self.bus.claim(self.bot)
                if action:
                    try:
                        result = await self.execute(action)
                        self.bus.finish(action["id"], result)
                    except (ValueError, discord.HTTPException) as exc:
                        self.bus.finish(action["id"], {"text": str(exc)[:1500]}, "error")
                    except Exception as exc:
                        log.exception("Dashboard-Auftrag fehlgeschlagen (%s)", type(exc).__name__)
                        self.bus.finish(action["id"], {"text": "Auftrag fehlgeschlagen. Bitte Bot-Protokoll prüfen."}, "error")
            except Exception as exc:
                log.error("Dashboard-Abgleich fehlgeschlagen (%s)", type(exc).__name__)
            await asyncio.sleep(2)

    async def beat(self):
        await self.client.wait_until_ready()
        while not self.client.is_closed():
            try:
                self.publish()
            except Exception as exc:
                log.error('Dashboard-Status fehlgeschlagen (%s)', type(exc).__name__)
            await asyncio.sleep(5)

    def event_links(self, guild_id, event_id):
        """Expose only an exact persisted event-to-Discord-message mapping."""
        row = self.client.service.store.db.execute(
            "SELECT * FROM message_index WHERE guild=? AND json_extract(metadata,'$.event_id')=? ORDER BY message DESC LIMIT 1",
            (guild_id, event_id)).fetchone()
        if not row:
            return {"source_url": None, "log_url": None, "source_deleted": False, "log_deleted": False}
        metadata = json.loads(row["metadata"])
        source_url = row["source_url"]
        source_deleted = bool(metadata.get("source_deleted") or metadata.get("deleted"))
        log_deleted = False
        refs = getattr(self.client, "event_refs", None)
        if refs:
            logged = refs.get(row["message"])
            if logged:
                log_deleted = bool(logged["deleted"])
                source_deleted = source_deleted or bool(logged["source_deleted"])
                source = refs.get(logged["source_message"]) if logged["source_message"] else None
                if source and source["guild"] == guild_id:
                    source_url = f"https://discord.com/channels/{source['guild']}/{source['channel']}/{source['message']}"
                    source_deleted = bool(source["deleted"])
        # Defend the response boundary even if a historic record was malformed.
        from .message_index import MESSAGE_URL
        match = MESSAGE_URL.fullmatch(source_url or "")
        if not match or int(match[1]) != guild_id:
            source_url = None
        return {"source_url": source_url, "log_url": f"https://discord.com/channels/{guild_id}/{row['channel']}/{row['message']}",
                "source_deleted": source_deleted, "log_deleted": log_deleted}

    def publish(self):
        service = self.client.service
        from .settings_schema import SCHEMA, COMMAND_DEFAULTS, CHANNEL_LABELS
        from .presentation import TEMPLATE_LABELS
        guilds = []
        for guild in self.client.guilds:
            settings = service.settings(guild.id)
            channels = []
            for ch in list(guild.channels) + list(guild.threads):
                if isinstance(ch, (discord.TextChannel, discord.ForumChannel, discord.Thread)):
                    channels.append({"id": ch.id, "name": ch.name, "type": str(ch.type),
                                     "parent": str(getattr(ch, "parent_id", None) or getattr(ch, "category_id", None) or ""),
                                     "sendable": isinstance(ch, (discord.TextChannel, discord.Thread))})
            stats = dict(service.store.db.execute("SELECT COUNT(*) AS active_members,COALESCE(SUM(messages),0) AS messages,COALESCE(SUM(xp),0) AS xp,COALESCE(SUM(voice_seconds),0) AS voice_seconds FROM activity WHERE guild=?", (guild.id,)).fetchone())
            stats["birthdays"] = service.store.db.execute("SELECT COUNT(*) FROM birthdays WHERE guild=?", (guild.id,)).fetchone()[0]
            stats["events"] = service.store.db.execute("SELECT COUNT(*) FROM events WHERE guild=?", (guild.id,)).fetchone()[0]
            stats["members"] = guild.member_count
            events = [dict(r) for r in service.store.db.execute("SELECT id,title,text,created FROM events WHERE guild=? ORDER BY id DESC LIMIT 30", (guild.id,))]
            for event in events:
                event.update(self.event_links(guild.id, event["id"]))
            moderators = [dict(r) for r in service.store.db.execute("SELECT id,actor,target,action,reason,created,status,metadata FROM moderation WHERE guild=? ORDER BY id DESC LIMIT 30", (guild.id,))]
            for row in moderators:
                metadata = json.loads(row.pop("metadata") or "{}")
                row["web_account"] = metadata.get("dashboard_account")
                row["target_name"] = metadata.get("target_name", str(row["target"]))
                row["notification_status"] = metadata.get("notification_status", "not_requested")
                row["notification_error"] = metadata.get("notification_error")
                row["invite_url"] = metadata.get("invite_url")
                row["actor_name"] = (row["web_account"]["display_name"] if row["web_account"] else metadata.get("actor_name"))
            leaders = [dict(r) for r in service.store.db.execute("SELECT user,xp,messages,voice_seconds FROM activity WHERE guild=? ORDER BY xp DESC LIMIT 10", (guild.id,))]
            for row in leaders:
                member = guild.get_member(row["user"])
                row["name"] = member.display_name if member else str(row["user"])
            protected = {int(r) for r in settings.get("protected_role_ids", [])}
            member_rows = []
            for m in sorted(guild.members, key=lambda m: m.display_name.casefold()):
                role_ids = [r.id for r in getattr(m, "roles", [])]
                owner = m.id in {OWNER_ID, getattr(guild, "owner_id", None)}
                timeout = getattr(m, "timed_out_until", None)
                member_rows.append({"id":m.id, "name":m.display_name, "username":str(m),
                    "role_ids":role_ids, "admin":bool(getattr(getattr(m, "guild_permissions", None), "administrator", False)),
                    "bot":bool(getattr(m, "bot", False)), "owner":owner, "protected":owner or bool(protected.intersection(role_ids)),
                    "timed_out_until":timeout.isoformat() if timeout else None})
            has_history = service.store.db.execute("SELECT 1 FROM sqlite_master WHERE name='moderation_targets'").fetchone()
            history = [dict(r) for r in service.store.db.execute("SELECT * FROM moderation_targets WHERE guild=? ORDER BY updated DESC", (guild.id,))] if has_history else []
            for row in history:
                row["banned"] = bool(row["banned"]) if row["banned"] is not None else None
                row["kicked"] = bool(row["kicked"])
            guilds.append({"id": guild.id, "name": guild.name, "icon": str(guild.icon.url) if guild.icon else None,
                           "channels": channels, "roles": [{"id": r.id, "name": r.name,
                               "administrator":bool(getattr(getattr(r,"permissions",None),"administrator",False)),
                               "permissions":str(getattr(getattr(r,"permissions",None),"value",0)), "position":getattr(r,"position",0)} for r in guild.roles if not r.is_default()],
                           "members": member_rows, "moderation_history": history,
                           "member_sync": {**getattr(self.client,"member_sync",{}).get(guild.id, {"status":"cached"}), "cached":len(guild.members),"expected":guild.member_count},
                           "settings": settings, "stats": stats, "events": events, "moderation": moderators, "leaders": leaders,
                           "index_count": service.store.db.execute('SELECT COUNT(*) FROM message_index WHERE guild=?', (guild.id,)).fetchone()[0],
                           "scans": [dict(r) for r in service.store.db.execute('SELECT * FROM history_scans WHERE guild=? ORDER BY updated DESC LIMIT 100', (guild.id,))],
                           "owner_present": guild.get_member(OWNER_ID) is not None})
        self.bus.publish(self.bot, {"online": self.client.is_ready(), "name": service.config.base["name"],
                                   "owner_id": OWNER_ID, "guilds": guilds, "schema": SCHEMA,
                                   "command_defaults": COMMAND_DEFAULTS, "channel_labels": CHANNEL_LABELS, "template_labels": TEMPLATE_LABELS})

    async def check_channel(self, guild, value):
        if not value:
            return
        ch = guild.get_channel_or_thread(int(value))
        if ch is None:
            try:
                ch = await guild.fetch_channel(int(value))
            except discord.NotFound:
                raise ValueError("Kanal oder Forum-Beitrag wurde nicht gefunden.") from None
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            raise ValueError("Bitte einen Textkanal oder einen konkreten Forum-Beitrag wählen. Das Forum selbst ist kein Nachrichtenkanal.")
        p = ch.permissions_for(guild.me)
        send = p.send_messages_in_threads if isinstance(ch, discord.Thread) else p.send_messages
        if not (p.view_channel and send and p.embed_links):
            raise ValueError("Der Bot braucht im Ziel Lesen, Schreiben und Links einbetten.")

    async def execute(self, action):
        account = self.bus.authorize_queued(action)
        guild = self.client.get_guild(int(action["guild"]))
        if not guild:
            raise ValueError("Der Bot ist mit diesem Server nicht verbunden.")
        # Local accounts act with explicitly delegated web rights. Discord permissions
        # are checked using the fixed controller; the actual web author is audited.
        try:
            owner = await guild.fetch_member(OWNER_ID)
        except discord.NotFound:
            raise ValueError("Basti muss Mitglied dieses Servers sein, um ihn zu verwalten.") from None
        payload = action["payload"]
        kind = action["kind"]
        if kind == "settings":
            from .settings_schema import apply_settings
            from .notifications import resolve_source_account
            patch = json.loads(json.dumps(payload["patch"]))
            for value in patch.get("channels", {}).values():
                await self.check_channel(guild, value)
            for source in patch.get("sources", []):
                source["account"] = await resolve_source_account(self.client.session, source["platform"], source["account"])
                await self.check_channel(guild, source.get("channel_id"))
            if patch.get('level_roles'):
                roles = {r.id:r for r in await guild.fetch_roles()}
                me = await guild.fetch_member(self.client.user.id)
                for value in patch['level_roles'].values():
                    role = roles.get(int(value))
                    if (not role or role.is_default() or role.managed or self.client.privileged_role(role)
                            or not me.guild_permissions.manage_roles or role >= me.top_role):
                        raise ValueError('Belohnungsrollen müssen nicht privilegiert sein und unter der Botrolle stehen. Der Bot braucht Rollen verwalten.')
            self.bus.authorize_queued(action)
            apply_settings(self.client.service, guild.id, patch)
            return {"text": "Einstellungen gespeichert. Neue Ausgaben verwenden sie sofort. Befehlsnamen und Beschreibungen mit ‚Befehle aktualisieren‘ übertragen."}
        if kind == "sync":
            from .slash_commands import refresh_commands
            self.bus.authorize_queued(action)
            await refresh_commands(self.client, guild.id)
            return {"text": "Deutsche Slash-Befehle bei Discord aktualisiert."}
        if kind == "scan":
            self.bus.authorize_queued(action)
            await self.client.index_history(guild)
            return {"text": "Rückscan abgeschlossen. Anzahl und Grenzen stehen in den Index-Protokollen."}
        if kind == "moderation":
            if payload.get("confirm") is not True:
                raise ValueError("Moderation muss ausdrücklich bestätigt werden.")
            command = payload.get("command", payload.get("action"))
            if command not in {"ban", "unban", "timeout", "kick", "untimeout", "reinvite"}:
                raise ValueError("Unbekannte Moderationsaktion.")
            target = str(payload["target"])
            if int(target) == OWNER_ID and command in {"ban", "timeout", "kick"}:
                raise ValueError("Basti ist dauerhaft vor Bot-Moderation geschützt.")
            reason = str(payload.get("reason", "")).strip()
            if not reason or len(reason) > 300:
                raise ValueError("Bitte einen Grund mit 1–300 Zeichen angeben.")
            args = [target] + ([str(payload.get("duration", "10m"))] if command == "timeout" else []) + [reason]
            message = SimpleNamespace(id=int(action["id"][:15], 16), guild=guild, author=owner,
                channel=SimpleNamespace(id=0), content="Dashboard: " + command, interaction=None, jump_url=None, dashboard=True,
                dashboard_account={key: account[key] for key in ("id", "username", "display_name")},
                dashboard_authorize=lambda: self.bus.authorize_queued(action),
                moderation_options={"notify":payload.get("notify",False),"invite_channel":payload.get("invite_channel")})
            self.bus.authorize_queued(action)
            reply = await self.client.moderation.execute(message, command, args)
            await self.client.flush_moderation(guild)
            return {"title": reply.title, "text": reply.text, **getattr(reply, "moderation_result", {"moderation_status":"not_executed", "notification_status":"not_requested"})}
        if kind == "send_embed":
            if payload.get("confirm") is not True:
                raise ValueError("Versand muss ausdrücklich bestätigt werden.")
            await self.check_channel(guild, payload["channel_id"])
            from .presentation import build_embed, validate_templates
            from .service import Reply
            config = self.client.service.settings(guild.id)
            template = payload["template"]
            config = {**config, "embed_templates": {**config.get("embed_templates", {}), "dashboard": template}}
            validate_templates(config['embed_templates'])
            key = payload.get("template_key")
            preview_context = None
            reply = Reply("Nachricht", "")
            if key:
                from .presentation import sample_template_context
                preview_context = sample_template_context(key, name=owner.display_name, server=guild.name, bot=config["name"])
                reply = Reply(preview_context["title"], preview_context["description"],
                    fields=[(item["name"],item["value"],item.get("inline",False)) for item in preview_context["fields"]])
                preview_context = {k:v for k,v in preview_context.items() if k not in {"fields","avatar","image"}}
            embed = build_embed(reply, config, member=owner, template_key="dashboard", context=preview_context)
            if key:
                embed.set_footer(text=(embed.footer.text or "")[:900] + " · Manuelle Beispielnachricht – kein echtes Ereignis")
            channel = guild.get_channel_or_thread(int(payload["channel_id"])) or await guild.fetch_channel(int(payload["channel_id"]))
            kwargs = {'embed':embed,'allowed_mentions':discord.AllowedMentions.none()}
            key = payload.get('template_key')
            if key in {'welcome','farewell','birthday'} and template.get('use_default_banner') and not template.get('image_url'):
                if not channel.permissions_for(guild.me).attach_files:
                    raise ValueError('Der Bot braucht Dateien anhängen, um diese Bildkarte zu senden.')
                from .image_cards import render_card
                avatar = None
                if isinstance(getattr(owner,"display_avatar",None),discord.Asset):
                    try:
                        avatar = await owner.display_avatar.replace(size=256).read()
                    except discord.HTTPException:
                        pass
                data = await asyncio.to_thread(render_card,key,name=owner.display_name,server=guild.name,style=template.get("image_style",{}),avatar_bytes=avatar)
                kwargs['file']=discord.File(BytesIO(data),filename=f'{key}.png')
                embed.set_image(url=f'attachment://{key}.png')
            try:
                self.bus.authorize_queued(action)
                sent = await channel.send(**kwargs)
            finally:
                if 'file' in kwargs:
                    kwargs['file'].close()
                    kwargs['file'].fp.close()
            self.client.index.record(sent, "dashboard", metadata={"web_account": {key: account[key] for key in ("id", "username", "display_name")}})
            return {"text": "Manuelle Beispielnachricht gesendet." if key else "Nachricht gesendet.", "url": sent.jump_url}
        raise ValueError("Unbekannte Dashboard-Funktion.")
