from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone
from io import BytesIO

import aiohttp
import discord
from discord.ext import tasks

from .cards import rank_card
from .image_cards import render_card
from .notifications import Fetcher, Notifications
from .moderation import Moderation, MOD_COMMANDS, OWNER_ID, user_id
from .message_index import MessageIndex, LogDetailsView, references, legacy_command_name, EventReferences, member_context
from .presentation import build_embed, infer_template
from .service import Actor, Reply, Service
from .slash_commands import make_tree

log = logging.getLogger(__name__)


class DiscordBot(discord.Client):
    def __init__(self, service: Service):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.moderation = True
        intents.presences = False
        intents.typing = False
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.service = service
        self.session = None
        self.notifications = None
        self.voice_clock = None
        self.next_poll = {}
        self.next_live_poll = {}
        self.command_times = {}
        self.role_retry = {}
        self.moderation = Moderation(service, self)
        self.log_lock = asyncio.Lock()
        self.index = MessageIndex(service.store.db)
        self.history_task = None
        self.member_sync_task = None
        self.member_sync = {}
        self.history_lock = asyncio.Lock()
        self.dashboard_bridge = None
        self.event_refs = None
        self.tree = make_tree(self)

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                             headers={"User-Agent": "Mittelkap-DiscordBots/0.1"})
        self.notifications = Notifications(self.service.store, Fetcher(self.session, self.service.config.root / "data" / "tiktok-auth.json"))
        if self.service.config.base.get("command_mode") == "slash":
            await self.tree.sync()
        self.add_view(LogDetailsView(self))
        from .dashboard_bridge import DashboardBridge
        self.dashboard_bridge = DashboardBridge(self)
        await self.dashboard_bridge.start()
        self.event_refs = EventReferences(self.dashboard_bridge.bus.db)
        self.maintenance.start()

    async def close(self):
        self.maintenance.cancel()
        if self.history_task:
            self.history_task.cancel()
            await asyncio.gather(self.history_task, return_exceptions=True)
        if self.member_sync_task:
            self.member_sync_task.cancel()
            await asyncio.gather(self.member_sync_task, return_exceptions=True)
        if self.dashboard_bridge:
            await self.dashboard_bridge.close()
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self):
        log.info("%s ist verbunden (%d Server).", self.service.config.base["name"], len(self.guilds))
        self.voice_clock = time.monotonic()
        if self.member_sync_task is None:
            self.member_sync_task = asyncio.create_task(self.refresh_directory(), name="Mitgliederverzeichnis")
        if self.history_task is None:
            self.history_task = asyncio.create_task(self.restore_history(), name="Nachrichtenindex")

    async def refresh_directory(self):
        """A bounded initial refresh, never an HTTP crawl on every dashboard heartbeat."""
        for guild in self.guilds:
            state = self.member_sync[guild.id] = {"status":"loading", "cached":len(guild.members), "expected":guild.member_count, "bans_status":"loading"}
            try:
                if not guild.chunked:
                    await asyncio.wait_for(guild.chunk(cache=True), timeout=90)
                state["status"] = "complete" if len(guild.members) >= (guild.member_count or 0) else "partial"
            except (discord.HTTPException, discord.ClientException, asyncio.TimeoutError):
                state["status"] = "partial"
            state.update(cached=len(guild.members), expected=guild.member_count)
            async def read_bans():
                # Only reconcile absence after the complete list has arrived.
                entries = [entry async for entry in guild.bans(limit=None)]
                seen = {entry.user.id for entry in entries}
                for entry in entries:
                    self.moderation.remember(guild.id, entry.user, "ban", entry.reason or "Grund von Discord nicht angegeben")
                db = self.service.store.db
                with db:
                    for row in db.execute("SELECT user FROM moderation_targets WHERE guild=? AND banned=1", (guild.id,)).fetchall():
                        if row["user"] not in seen:
                            db.execute("UPDATE moderation_targets SET banned=0 WHERE guild=? AND user=?", (guild.id,row["user"]))
            try:
                if not (guild.me.guild_permissions.ban_members or guild.me.guild_permissions.view_audit_log):
                    state["bans_status"] = "missing_permission"
                else:
                    await asyncio.wait_for(read_bans(), timeout=90)
                    state["bans_status"] = "complete"
            except (discord.HTTPException, asyncio.TimeoutError):
                state["bans_status"] = "partial"
            state["updated"] = datetime.now(timezone.utc).isoformat()

    async def on_disconnect(self):
        # No XP for time while disconnected or for unknown voice participation.
        self.voice_clock = None

    def actor(self, member: discord.Member):
        c = self.service.settings(member.guild.id)
        configured = {str(r) for r in c["admin_role_ids"] + c.get("moderator_role_ids", [])}
        admin = any(str(role.id) in configured for role in member.roles) if configured else member.guild_permissions.manage_guild
        admin = admin or member.id in {OWNER_ID, getattr(member.guild, "owner_id", None)}
        roles = tuple(role.name for role in reversed(member.roles) if not role.is_default())
        return Actor(member.guild.id, member.id, member.display_name, admin, member.joined_at, member.top_role.name, roles)

    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or message.webhook_id or not isinstance(message.author, discord.Member):
            return
        c = self.service.settings(message.guild.id)
        parsed = self.service.parse(message.guild.id, message.content) if c.get("prefix_commands_enabled", True) and not message.content.startswith("/") else None
        is_command = parsed is not None or message.content.startswith(("!", "/"))
        if "activity" in c["features"] and not is_command:
            voice_attachments = [a for a in getattr(message, "attachments", []) if a.is_voice_message()]
            self.service.store.message(message.guild.id, message.author.id, time.time(), c["text_xp"],
                                       c["text_cooldown_seconds"], not voice_attachments and len(message.content.strip()) >= c["minimum_message_length"],
                                       getattr(message, "id", None))
            durations = [a.duration for a in voice_attachments if isinstance(a.duration, (int, float)) and math.isfinite(a.duration) and 0 < a.duration < 2**31]
            if durations:
                self.service.store.voice_message(message.guild.id, message.author.id, message.id, int(sum(durations)), c.get("voice_message_xp_per_minute", 10))
        if parsed:
            await self.dispatch_command(message, parsed)
        if "activity" in c["features"]:
            await self.sync_roles(message.author, c)

    async def dispatch_command(self, message, parsed):
        c = self.service.settings(message.guild.id)
        key = message.guild.id, message.author.id
        now = time.monotonic()
        if now - self.command_times.get(key, -10) < 1:
            await self.send_reply(message.channel, Reply("Kurz warten", "Bitte einen Moment zwischen Befehlen lassen."), c)
            return
        self.command_times[key] = now
        if len(self.command_times) > 10000:
            self.command_times = {k: v for k, v in self.command_times.items() if now - v < 60}
        actor = self.actor(message.author)
        if parsed[0] in MOD_COMMANDS:
            reply = await self.moderation.execute(message, *parsed)
            await self.send_reply(message.channel, reply, c)
            await self.flush_moderation(message.guild)
        elif parsed[0] == "congratulate":
            await self.congratulate(message, parsed[1], c)
        elif parsed[0] == "rank" and parsed[1]:
            if len(parsed[1]) != 1 or not re.fullmatch(r"<@!?\d+>", parsed[1][0]):
                await self.send_reply(message.channel, Reply("Eingabe prüfen", "Bitte /rang mit optional ausgewähltem Mitglied verwenden."), c)
                return
            user = int(parsed[1][0].strip("<@!>"))
            member = message.guild.get_member(user)
            if member is None:
                await self.send_reply(message.channel, Reply("Mitglied nicht gefunden", "Dieses Mitglied ist auf dem Server nicht verfügbar."), c)
                return
            target = self.actor(member)
            reply = self.service.rank(target) if "rank" in c["features"] else self.service.handle(actor, message.content)
            await self.send_reply(message.channel, reply, c, member)
        elif await self.validate_admin_target(message, parsed, actor):
            reply = self.service.handle(actor, message.content)
            target = message.channel
            if reply and reply.channel_key and c["channels"].get(reply.channel_key) and not getattr(message.channel, "ephemeral", False):
                target = await self.resolve_channel(message.guild, int(c["channels"][reply.channel_key]))
                if not isinstance(target, (discord.TextChannel, discord.Thread)):
                    await self.send_reply(message.channel, Reply("Zielkanal prüfen", "Der konfigurierte Ausgabekanal ist nicht mehr verfügbar."), c)
                    return
            sent = await self.send_reply(target, reply, c, message.author)
            if sent and target is not message.channel:
                await self.send_reply(message.channel, Reply("Gesendet", f"Die Antwort steht in <#{target.id}>."), c)

    async def validate_admin_target(self, message, parsed, actor):
        command, args = parsed
        if not actor.admin:
            return True  # The service reports the permission denial and performs no mutation.
        if command == "setup" and len(args) == 2 and args[1].casefold() != "aus":
            value = args[1].strip("<#>")
            target = await self.resolve_channel(message.guild, int(value)) if value.isdigit() else None
            me = message.guild.me
            if (not isinstance(target, (discord.TextChannel, discord.Thread)) or not me or
                    not all((target.permissions_for(me).view_channel, (target.permissions_for(me).send_messages_in_threads if isinstance(target, discord.Thread) else target.permissions_for(me).send_messages),
                             target.permissions_for(me).embed_links))):
                await self.send_reply(message.channel, Reply("Kanal prüfen", "Bitte einen Textkanal oder Forum-Beitrag dieses Servers wählen, in dem ich sehen, schreiben und Links einbetten darf."), self.service.settings(actor.guild))
                return False
        if command == "rollen" and len(args) == 2 and args[1].casefold() != "aus":
            value = args[1].strip("<@&>")
            role = message.guild.get_role(int(value)) if value.isdigit() else None
            issuer = message.author
            privileged = role and self.privileged_role(role)
            if (role is None or not role.is_assignable() or not message.guild.me.guild_permissions.manage_roles
                    or (issuer.id != OWNER_ID and not issuer.guild_permissions.manage_roles) or privileged
                    or (issuer.id not in {message.guild.owner_id, OWNER_ID} and role >= issuer.top_role)):
                await self.send_reply(message.channel, Reply("Rolle prüfen", "Die Rolle muss auf diesem Server existieren und unter meiner höchsten Rolle liegen. Ich brauche „Rollen verwalten“."), self.service.settings(actor.guild))
                return False
        return True

    async def resolve_channel(self, guild, channel_id):
        if not channel_id:
            return None
        getter = getattr(guild, "get_channel_or_thread", guild.get_channel)
        channel = getter(int(channel_id))
        if channel is None and hasattr(guild, "fetch_channel"):
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except discord.HTTPException:
                return None
        channel_guild = getattr(getattr(channel, "guild", None), "id", None)
        if isinstance(channel_guild, int) and channel_guild != guild.id:
            return None
        return channel

    async def send_reply(self, channel, reply: Reply | None, c: dict, member=None, *, template_key="default", category=None, metadata=None, return_message=False):
        if reply is None:
            return False
        command_key = getattr(channel, "category", None)
        if template_key == "default" and isinstance(command_key, str):
            template_key = command_key
        embed = build_embed(reply, c, member, template_key)
        kwargs = {"embed": embed, "allowed_mentions": discord.AllowedMentions.none()}
        custom_template = c.get("embed_templates", {}).get(template_key, {})
        if (template_key in {"welcome", "farewell", "birthday"} and not custom_template.get('image_url')
                and custom_template.get('use_default_banner', 'image_url' not in custom_template)):
            guild = getattr(member, "guild", None) or getattr(channel, "guild", None)
            if guild and channel.permissions_for(guild.me).attach_files:
                avatar = None
                if member and isinstance(getattr(member, "display_avatar", None), discord.Asset):
                    try:
                        avatar = await member.display_avatar.with_size(256).with_format("png").read()
                    except discord.HTTPException:
                        pass
                card = await asyncio.to_thread(render_card, template_key,
                    name=getattr(member, "display_name", "Community"), server=guild.name,
                    style=custom_template.get("image_style", {}), avatar_bytes=avatar if isinstance(avatar, bytes) else None)
                kwargs["file"] = discord.File(BytesIO(card), filename=f"{template_key}.png")
                embed.set_image(url=f"attachment://{template_key}.png")
        guild_id = getattr(getattr(channel, "guild", None), "id", None)
        source_url, channel_url = references(reply, guild_id if isinstance(guild_id, int) else None)
        is_log = category in {"logs", "moderation", "message_edit", "message_delete"}
        deleted = "gelöscht" in reply.title.casefold() and "nachricht" in reply.title.casefold()
        if is_log:
            kwargs["view"] = LogDetailsView(self, source_url, channel_url, deleted=deleted)
        if reply.rank:
            avatar = None
            if member:
                try:
                    avatar = await member.display_avatar.with_size(128).with_format("png").read()
                except discord.HTTPException:
                    log.warning("Profilbild konnte nicht geladen werden; Rangkarte verwendet Ersatzbild.")
            card = await asyncio.to_thread(rank_card, reply.rank, c["name"], c["color"], avatar)
            kwargs["file"] = discord.File(BytesIO(card), filename="rang.png")
            embed.set_image(url="attachment://rang.png")
        try:
            sent = await channel.send(**kwargs)
            reply_category = category or getattr(channel, "category", "reply")
            self.index.record(sent, reply_category if isinstance(reply_category, str) else "reply", source_url,
                              {"title": reply.title, "deleted": deleted, **(metadata or {})})
            return sent if return_message else True
        except discord.HTTPException as exc:
            log.warning("Antwort konnte nicht gesendet werden (%s).", type(exc).__name__)
            return False
        finally:
            if "file" in kwargs:
                kwargs["file"].close()
                kwargs["file"].fp.close()

    async def restore_history(self):
        for guild in self.guilds:
            try:
                await self.index_history(guild)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Nachrichtenindex für Server %s nicht vollständig (%s).", guild.id, type(exc).__name__)

    async def index_history(self, guild):
        async with self.history_lock:
            return await self._index_history(guild)

    async def _index_history(self, guild):
        from .settings_schema import COMMAND_DEFAULTS, command_options
        c = self.service.settings(guild.id)
        configured = {(key, int(value)) for key, value in c["channels"].items() if value}
        targets = configured | set(self.index.scopes(guild.id))
        for command, settings in c.get("command_settings", {}).items():
            targets.update((command, int(ch)) for ch in settings.get("allowed_channel_ids", []))
        command_names = {command_options(c, command)["name"]: command for command in COMMAND_DEFAULTS}
        results = []
        for category, channel_id in sorted(targets):
            raw_limit = c.get("history_scan_overrides", {}).get(category, c.get("history_scan_limit", 50))
            limit = None if raw_limit == "all" else int(raw_limit)
            if limit == 0:
                self.index.scan_status(guild.id, category, channel_id, 0, 0, "deaktiviert")
                continue
            channel = await self.resolve_channel(guild, channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                self.index.scan_status(guild.id, category, channel_id, 0, 0, "Ziel nicht verfügbar")
                continue
            examined = indexed = 0
            status = "abgeschlossen"
            seen_messages = set()
            oldest_examined = 0
            # Exclude messages created after this scan started from absence checks.
            scan_upper_bound = discord.utils.time_snowflake(datetime.now(timezone.utc))
            try:
                # Count matching BOT messages, not unrelated member chat. A deep search
                # can require more history reads; discord.py handles paging/rate limits.
                async for message in channel.history(limit=None):
                    examined += 1
                    oldest_examined = message.id
                    if examined % 50 == 0:
                        self.index.scan_status(guild.id, category, channel_id, examined, indexed, "läuft")
                        await asyncio.sleep(0)
                    if message.author.id != self.user.id:
                        continue
                    seen_messages.add(message.id)
                    previous = self.index.get(message.id)
                    known_category = previous["category"] if previous else command_names.get(legacy_command_name(message))
                    if category in COMMAND_DEFAULTS and known_category != category:
                        continue
                    if known_category and known_category != category:
                        continue
                    embeds = message.embeds
                    history_reply = Reply(embeds[0].title or "Botantwort" if embeds else "Botantwort",
                                          embeds[0].description or "" if embeds else "",
                                          fields=[(field.name, field.value, field.inline) for embed in embeds for field in embed.fields])
                    source_url, _ = references(history_reply, guild.id)
                    name = known_category or category
                    self.index.record(message, name, source_url,
                                      {"title": embeds[0].title or "Botantwort" if embeds else "Botantwort",
                                       "deleted": bool(embeds and "Nachricht gelöscht" in (embeds[0].title or ""))})
                    event = member_context(message, name, previous)
                    if event and self.event_refs:
                        self.event_refs.record(message, event, "announcement" if name in {"welcome", "farewell"} else "log", c["persona"])
                        self.index.link(message.id, source_url or (previous or {}).get("source_url"), event)
                    indexed += 1
                    # URL buttons work on their own. Restore interactive details on legacy logs only.
                    if category in {"logs", "moderation"} and not message.components:
                        reply = history_reply
                        origin, source_channel = references(reply, guild.id)
                        origin = origin or source_url
                        try:
                            await message.edit(view=LogDetailsView(self, origin, source_channel, "Nachricht gelöscht" in reply.title))
                        except discord.HTTPException:
                            pass
                    if limit is not None and indexed >= limit:
                        break
            except discord.Forbidden:
                status = "Leserechte fehlen"
            except discord.HTTPException:
                status = "Discord-Abfrage unterbrochen"
            if status == "abgeschlossen" and self.event_refs:
                self.event_refs.mark_missing(guild.id, channel_id, c["persona"], seen_messages, oldest_examined, scan_upper_bound)
            self.index.scan_status(guild.id, category, channel_id, examined, indexed, status)
            results.append({"category": category, "channel": str(channel_id), "examined": examined, "indexed": indexed, "status": status})
        await self.repair_event_links(guild)
        return results

    async def congratulate(self, message, args, c):
        if "birthdays" not in c["features"]:
            await self.send_reply(message.channel, Reply("Aufgabenverteilung", "Geburtstagsgrüße sind für diesen Bot nicht aktiviert."), c)
            return
        try:
            if not args:
                raise ValueError("Syntax: Glückwunsch @Mitglied [deine Nachricht]")
            target_id = user_id(args[0])
            target = message.guild.get_member(target_id)
            if target is None or target.bot or not self.service.store.birthday(message.guild.id, target_id):
                raise ValueError("Das Ziel muss ein aktuelles Mitglied mit freiwillig eingetragenem Geburtstag sein.")
            if len(" ".join(args[1:])) > 500:
                raise ValueError("Deine Nachricht darf höchstens 500 Zeichen enthalten.")
            from zoneinfo import ZoneInfo
            today = datetime.now(timezone.utc).astimezone(ZoneInfo(c["timezone"])).date().isoformat()
            delivery = f"congratulate:{message.author.id}:{target_id}:{today}"
            if self.service.store.seen(message.guild.id, delivery):
                raise ValueError("Deinen Glückwunsch an dieses Mitglied habe ich heute bereits übermittelt.")
            destination = await self.resolve_channel(message.guild, int(c["channels"]["birthdays"] or 0)) if c["channels"]["birthdays"] else message.channel
            if not isinstance(destination, (discord.TextChannel, discord.Thread)) and not hasattr(destination, "interaction"):
                raise ValueError("Bitte den eingestellten Geburtstagskanal prüfen.")
            text = " ".join(args[1:]) or "Alles Gute zum Geburtstag!"
            reply = Reply("Persönlicher Glückwunsch", f"Von {message.author.display_name} an {target.display_name}:\n{text}")
            if await self.send_reply(destination, reply, c):
                self.service.store.mark(message.guild.id, delivery)
                if destination is not message.channel:
                    await self.send_reply(message.channel, Reply("Glückwunsch gesendet", f"Dein Glückwunsch steht in <#{destination.id}>."), c)
        except ValueError as exc:
            await self.send_reply(message.channel, Reply("Eingabe prüfen", str(exc)), c)

    async def flush_moderation(self, guild):
        c = self.service.settings(guild.id)
        channel = await self.resolve_channel(guild, int(c["channels"].get("moderation") or c["channels"]["logs"] or 0))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        async with self.log_lock:
            for audit in self.service.store.moderation_outbox(guild.id):
                if await self.send_reply(channel, self.moderation.audit_reply(audit), c, template_key="moderation", category="moderation"):
                    self.service.store.moderation_delivered(audit["id"])
                else:
                    break

    async def sync_roles(self, member, c):
        if not c["level_roles"] or member.bot or not member.guild.me or not member.guild.me.guild_permissions.manage_roles:
            return
        key = member.guild.id, member.id
        if time.monotonic() < self.role_retry.get(key, 0):
            return
        level = self.service.store.stats(member.guild.id, member.id)["level"]
        current = {r.id for r in member.roles}
        wanted = [member.guild.get_role(int(role)) for threshold, role in c["level_roles"].items()
                  if level >= int(threshold) and int(role) not in current]
        wanted = [role for role in wanted if role and role.is_assignable() and not self.privileged_role(role)]
        if wanted:
            try:
                await member.add_roles(*wanted, reason=f"Aktivitätslevel {level}")
            except discord.HTTPException as exc:
                self.role_retry[key] = time.monotonic() + 300
                log.warning("Levelrollen konnten nicht vergeben werden (%s).", type(exc).__name__)

    @staticmethod
    def privileged_role(role):
        return any(getattr(role.permissions, name, False) for name in (
            "administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members", "kick_members",
            "moderate_members", "manage_webhooks", "manage_messages", "manage_threads", "mute_members", "deafen_members",
            "move_members", "manage_nicknames", "view_audit_log", "manage_events", "manage_expressions", "mention_everyone"))

    async def event_log(self, guild, title, text, event_key=None, metadata=None):
        if metadata:
            event_key = event_key or f"structured:{time.time_ns()}"
            self.index.event_context(guild.id, event_key, metadata)
        self.service.store.record_event(guild.id, title, text, event_key)
        await self.flush_events(guild)

    @staticmethod
    def event_details(member, joined):
        joined_at = getattr(member, "joined_at", None)
        membership = joined_at.isoformat() if isinstance(joined_at, datetime) else ""
        moment = joined_at.timestamp() if joined and isinstance(joined_at, datetime) else time.time()
        return {"member_event": "join" if joined else "leave", "member_id": member.id,
                "member_name": member.display_name, "membership": membership, "event_time": moment}

    @staticmethod
    def reference_field(context, source):
        label = "Willkommensnachricht" if context["member_event"] == "join" else "Abschiedsnachricht"
        if source and not source["deleted"]:
            return (label, f"[Nachricht öffnen](https://discord.com/channels/{source['guild']}/{source['channel']}/{source['message']})", False)
        if source:
            return (label, "Die zugehörige Nachricht wurde gelöscht. Der gespeicherte Bezug bleibt erhalten; die Nachricht ist nicht mehr aufrufbar.", False)
        return (label, "Noch kein eindeutiger Nachrichtenbezug verfügbar. Er wird ergänzt, sobald die passende Botnachricht erkannt wurde.", False)

    async def flush_events(self, guild):
        c = self.service.settings(guild.id)
        channel = await self.resolve_channel(guild, int(c["channels"]["logs"] or 0))
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            async with self.log_lock:
                for event in self.service.store.event_outbox(guild.id):
                    context = self.index.event_context(guild.id, event.get("event_key"))
                    reply = Reply(event["title"], context.get("summary", event["text"]), timestamp=event["created"], fields=context.get("fields", []))
                    source = None
                    if context.get("member_event"):
                        source = self.event_refs.match(context, guild.id) if self.event_refs else None
                        # Let the other bot finish its announcement without delaying unrelated logs.
                        if self.event_refs and not source and time.time() - datetime.fromisoformat(event["created"]).timestamp() < 5:
                            continue
                        member_id = context["member_id"]
                        display = discord.utils.escape_markdown(context.get("member_name", "Mitglied"))
                        reply.text = "Ein neues Mitglied ist unserer Community beigetreten." if context["member_event"] == "join" else "Ein Mitglied hat unsere Community verlassen."
                        reply.fields = [("👤 Mitglied", f"**{display}**\n[Profil öffnen](https://discord.com/users/{member_id}) · `{member_id}`", False),
                                        ("🕒 Ereignis", f"<t:{int(context['event_time'])}:F>\n<t:{int(context['event_time'])}:R>", True),
                                        ("🌐 Server", f"{guild.name}\n`{guild.id}`", True),
                                        self.reference_field(context, source)]
                    sent = await self.send_reply(channel, reply, c, template_key=infer_template(event["title"]) if infer_template(event["title"]) != "default" else "logs", category="logs", metadata={**context, "event_id": event["id"], "event_key": event.get("event_key")}, return_message=True)
                    if sent:
                        if context.get("member_event") and self.event_refs:
                            self.event_refs.record(sent, context, "log", c["persona"])
                            if source and isinstance(getattr(sent, "id", None), int):
                                self.event_refs.bind(sent.id, source)
                                self.index.link(sent.id, f"https://discord.com/channels/{source['guild']}/{source['channel']}/{source['message']}", {"source_deleted": bool(source["deleted"])})
                        self.service.store.event_delivered(event["id"])
                    else:
                        break

    async def repair_event_links(self, guild):
        if not self.event_refs:
            return
        for position, record in enumerate(self.event_refs.pending(guild.id, self.service.config.base["persona"])):
            if position % 50 == 0:
                await asyncio.sleep(0)
            context = {"member_event": record["event"], "member_id": record["user"], "membership": record["membership"], "event_time": record["event_time"]}
            source = self.event_refs.get(record["source_message"]) if record["source_message"] else self.event_refs.match(context, guild.id, record["message"])
            if not source:
                continue
            channel = await self.resolve_channel(guild, record["channel"])
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                continue
            try:
                message = await channel.fetch_message(record["message"])
                if message.author.id != self.user.id or not message.embeds:
                    continue
                embed = message.embeds[0].copy()
                for position in reversed(range(len(embed.fields))):
                    if embed.fields[position].name in {"Willkommensnachricht", "Abschiedsnachricht"}:
                        embed.remove_field(position)
                field = self.reference_field(context, source)
                embed.add_field(name=field[0], value=field[1], inline=False)
                if len(embed) > 5900 and embed.description:
                    embed.description = embed.description[:max(0, len(embed.description) - (len(embed) - 5900))]
                while len(embed) > 5900 and len(embed.fields) > 1:
                    embed.remove_field(len(embed.fields) - 2)
                source_url = f"https://discord.com/channels/{source['guild']}/{source['channel']}/{source['message']}"
                await message.edit(embed=embed, view=LogDetailsView(self, source_url, f"https://discord.com/channels/{source['guild']}/{source['channel']}", deleted=bool(source["deleted"])))
                self.index.link(message.id, source_url, {**context, "source_deleted": bool(source["deleted"])})
                self.event_refs.bind(message.id, source)
            except discord.NotFound:
                self.event_refs.mark_deleted(record["message"])
            except discord.HTTPException as exc:
                log.warning("Ereignisverweis konnte noch nicht ergänzt werden (%s).", type(exc).__name__)

    async def member_announcement(self, member, joined):
        c = self.service.settings(member.guild.id)
        reply = self.service.member_event(member.guild.id, member.id, member.display_name, joined, member.guild.name, member.guild.member_count or 0)
        if not member.bot and reply:
            key = "welcome" if joined else "farewell"
            channel = await self.resolve_channel(member.guild, int(c["channels"].get(key) or c["channels"]["logs"] or 0))
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                reply.fields.extend([
                    ("👤 Mitglied", f"{member.display_name}\n`{member.id}`", True),
                    ("🌐 Community", f"{member.guild.name}\n{member.guild.member_count or 0} Mitglieder", True),
                ])
                created = getattr(member, "created_at", None)
                if isinstance(created, datetime):
                    reply.fields.append(("📆 Discord-Konto", f"<t:{int(created.timestamp())}:D> · <t:{int(created.timestamp())}:R>", False))
                if joined:
                    reply.fields.append(("🧭 Dein Start", "Mit `/hilfe` entdeckst du alle Funktionen. Unter `/geburtstag` kannst du freiwillig deinen Geburtstag eintragen; `/rang` zeigt deine Aktivität.", False))
                else:
                    joined_at = getattr(member, "joined_at", None)
                    if isinstance(joined_at, datetime):
                        reply.fields.append(("🕰️ Auf dem Server seit", f"<t:{int(joined_at.timestamp())}:F>", False))
                context = self.event_details(member, joined)
                sent = await self.send_reply(channel, reply, c, member, template_key=key, category=key, metadata=context, return_message=True)
                if sent and self.event_refs:
                    self.event_refs.record(sent, context, "announcement", c["persona"])
                return sent
        return None

    async def on_member_join(self, member):
        self.moderation.remember(member.guild.id, member, "join", "Dem Server beigetreten")
        c = self.service.settings(member.guild.id)
        await self.member_announcement(member, True)
        if "server_logs" in c["features"]:
            context = self.event_details(member, True)
            await self.event_log(member.guild, "Mitglied beigetreten", f"Mitglied: {member.id} · {member.display_name}",
                f"member:join:{member.id}:{context['membership'] or context['event_time']}", metadata=context)
        if "activity" in c["features"]:
            await self.sync_roles(member, c)

    async def on_member_remove(self, member):
        await self.member_announcement(member, False)
        if "server_logs" in self.service.settings(member.guild.id)["features"]:
            context = self.event_details(member, False)
            await self.event_log(member.guild, "Mitglied ausgetreten", f"Mitglied: {member.id} · {member.display_name}",
                f"member:leave:{member.id}:{context['membership'] or context['event_time']}", metadata=context)

    async def on_member_update(self, before, after):
        if "server_logs" not in self.service.settings(after.guild.id)["features"]:
            return
        old, new = {r.id: r.name for r in before.roles}, {r.id: r.name for r in after.roles}
        changes = []
        if old.keys() != new.keys():
            changes.append("Rollen hinzugefügt: " + (", ".join(new[r] for r in new.keys() - old.keys()) or "keine"))
            changes.append("Rollen entfernt: " + (", ".join(old[r] for r in old.keys() - new.keys()) or "keine"))
        if before.nick != after.nick:
            changes.append(f"Spitzname: {before.nick or 'keiner'} → {after.nick or 'keiner'}")
        if changes:
            await self.event_log(after.guild, "Mitglied geändert", f"Mitglied: {after.id}\n" + "\n".join(changes)[:2500])

    async def on_member_ban(self, guild, user):
        self.moderation.remember(guild.id, user, "ban", "Bann von Discord bestätigt; Grund siehe Moderationsprotokoll")
        if "server_logs" in self.service.settings(guild.id)["features"] and not guild.me.guild_permissions.view_audit_log:
            await self.event_log(guild, "Mitglied gebannt", f"Nutzer: {user.id}\nModerator und Grund sind ohne Audit-Log-Zugriff unbekannt.")

    async def on_member_unban(self, guild, user):
        self.moderation.remember(guild.id, user, "unban", "Entbannung von Discord bestätigt")
        if "server_logs" in self.service.settings(guild.id)["features"] and not guild.me.guild_permissions.view_audit_log:
            await self.event_log(guild, "Mitglied entbannt", f"Nutzer: {user.id}\nModerator und Grund sind ohne Audit-Log-Zugriff unbekannt.")

    async def on_audit_log_entry_create(self, entry):
        observed = {discord.AuditLogAction.ban:"ban",discord.AuditLogAction.unban:"unban",discord.AuditLogAction.kick:"kick"}.get(entry.action)
        if observed and getattr(entry.target,"id",None):
            self.moderation.remember(entry.guild.id, entry.target, observed, entry.reason or "Grund von Discord nicht angegeben", created=entry.created_at.isoformat() if getattr(entry, "created_at", None) else None)
        if "server_logs" not in self.service.settings(entry.guild.id)["features"]:
            return
        names = {discord.AuditLogAction.ban: "Bann", discord.AuditLogAction.unban: "Entbannung", discord.AuditLogAction.kick: "Kick",
                 discord.AuditLogAction.role_create: "Rolle erstellt", discord.AuditLogAction.role_update: "Rolle geändert", discord.AuditLogAction.role_delete: "Rolle gelöscht",
                 discord.AuditLogAction.member_role_update: "Mitgliedsrollen geändert"}
        if entry.action == discord.AuditLogAction.member_update and hasattr(entry.after, "timed_out_until"):
            title = "Timeout geändert"
        else:
            title = names.get(entry.action)
        if not title:
            return
        if self.user and entry.user_id == self.user.id and entry.action in {discord.AuditLogAction.ban, discord.AuditLogAction.unban, discord.AuditLogAction.kick}:
            return  # Own moderation commands have a durable, more detailed action record.
        target = getattr(entry.target, "id", "unbekannt")
        details = f"**Ziel:** {entry.target}\n[Profil / ID {target}](https://discord.com/users/{target})\n"
        details += f"**Ausführender Account:** {getattr(entry, 'user', None) or entry.user_id}\n[Profil / ID {entry.user_id}](https://discord.com/users/{entry.user_id})\n"
        details += f"**Grund:** {entry.reason or 'Von Discord nicht angegeben'}\n**Audit-ID:** {entry.id}\n"
        details += f"**Server:** {entry.guild.name} ({entry.guild.id})\n[Server / Logkanal öffnen](https://discord.com/channels/{entry.guild.id}/{self.service.settings(entry.guild.id)['channels']['logs']})"
        created = getattr(entry, "created_at", None)
        if created:
            details += f"\n**Zeitpunkt (UTC):** {created.isoformat()}"
        changes = getattr(entry, "changes", None)
        if changes:
            for label in ("before", "after"):
                diff = getattr(changes, label, None)
                if diff:
                    values = "; ".join(f"{key}: {value}" for key, value in diff)
                    if values:
                        details += f"\n**{'Vorher' if label == 'before' else 'Nachher'}:** {values[:1000]}"
        if title == "Timeout geändert":
            details += f"\nTimeout bis: {entry.after.timed_out_until or 'aufgehoben'}"
        await self.event_log(entry.guild, title, details, f"discord-audit:{entry.id}")

    async def on_raw_message_delete(self, payload):
        if self.event_refs:
            self.event_refs.mark_deleted(payload.message_id)
        if not payload.guild_id:
            return
        c = self.service.settings(payload.guild_id)
        guild = self.get_guild(payload.guild_id)
        if not guild or "message_logs" not in c["features"] or payload.channel_id == int(c["channels"]["logs"] or 0):
            return
        message = payload.cached_message
        if message and message.author.bot:
            return
        text = f"Kanal: <#{payload.channel_id}> · Nachricht: {payload.message_id}"
        if message:
            text += f"\nAutor: {message.author} · [ID {message.author.id}](https://discord.com/users/{message.author.id})"
            text += f"\nNachricht erstellt (UTC): {message.created_at.isoformat()}"
            if c["log_message_content"]:
                text += "\nInhalt: " + discord.utils.escape_markdown(message.content[:1200])
        else:
            text += "\nNachricht war nicht im Cache; Inhalt und Autor sind unbekannt."
        text += f"\n[Kanal öffnen](https://discord.com/channels/{payload.guild_id}/{payload.channel_id})\nEhemaliger Nachrichtenverweis: https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}\nDie ursprüngliche Nachricht ist gelöscht und kann nicht mehr geöffnet werden."
        original = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        fields = [("💬 Kanal", f"<#{payload.channel_id}>\n`{payload.channel_id}`", True),
                  ("Nachricht", f"`{payload.message_id}`\nGelöscht · ehemaliger Verweis: {original}", False),
                  ("👤 Autor", f"{discord.utils.escape_markdown(str(message.author))}\n[Profil öffnen](https://discord.com/users/{message.author.id}) · `{message.author.id}`" if message else "Von Discord nicht mehr bereitgestellt.", False),
                  ("🛡️ Gelöscht durch", "Nicht eindeutig aus dem Nachrichtenereignis bestimmbar.", False)]
        if message and c["log_message_content"]:
            fields.append(("📝 Letzter verfügbarer Inhalt", discord.utils.escape_markdown(message.content[:1000]) or "Kein Textinhalt.", False))
        await self.event_log(guild, "Nachricht gelöscht", text, metadata={"summary": "Eine Nachricht wurde entfernt. Der gespeicherte Verweis dokumentiert ihren früheren Ort; gelöschte Nachrichten lassen sich nicht öffnen.", "fields": fields})

    async def on_raw_message_edit(self, payload):
        if not payload.guild_id or "content" not in payload.data:
            return
        c = self.service.settings(payload.guild_id)
        guild = self.get_guild(payload.guild_id)
        if not guild or "message_logs" not in c["features"] or payload.channel_id == int(c["channels"]["logs"] or 0):
            return
        old = payload.cached_message
        if payload.data.get("author", {}).get("bot") or (old and old.author.bot):
            return
        if old and old.content == payload.data["content"]:
            return
        text = f"Kanal: <#{payload.channel_id}> · Nachricht: {payload.message_id}"
        author = old.author if old else None
        author_id = author.id if author else payload.data.get("author", {}).get("id")
        author_name = str(author) if author else payload.data.get("author", {}).get("username", "von Discord nicht bereitgestellt")
        text += f"\nAutor: {author_name}" + (f" · [ID {author_id}](https://discord.com/users/{author_id})" if author_id else "")
        if payload.data.get("edited_timestamp"):
            text += f"\nBearbeitet (UTC): {payload.data['edited_timestamp']}"
        text += f"\n[Nachricht öffnen](https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id})"
        if c["log_message_content"]:
            text += "\nVorher: " + (discord.utils.escape_markdown(old.content[:800]) if old else "nicht im Cache")
            text += "\nNachher: " + discord.utils.escape_markdown(payload.data["content"][:800])
        original = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        fields = [("💬 Kanal", f"<#{payload.channel_id}>\n`{payload.channel_id}`", True),
                  ("Nachricht", f"[Nachricht öffnen]({original})\n`{payload.message_id}`", True),
                  ("👤 Autor", discord.utils.escape_markdown(author_name) + (f"\n[Profil öffnen](https://discord.com/users/{author_id}) · `{author_id}`" if author_id else "\nID von Discord nicht bereitgestellt."), False)]
        if c["log_message_content"]:
            fields.extend([("− Vorher", discord.utils.escape_markdown(old.content[:1000]) if old else "Nicht im Cache; früherer Inhalt unbekannt.", False),
                           ("+ Nachher", discord.utils.escape_markdown(payload.data["content"][:1000]) or "Kein Textinhalt.", False)])
        await self.event_log(guild, "Nachricht bearbeitet", text, metadata={"summary": "Der Inhalt einer Nachricht wurde geändert. Die Gegenüberstellung zeigt ausschließlich die von Discord verfügbaren Texte.", "fields": fields})

    @tasks.loop(seconds=30)
    async def maintenance(self):
        now = datetime.now(timezone.utc)
        clock = time.monotonic()
        elapsed = max(0, int(clock - self.voice_clock)) if self.voice_clock is not None else 0
        self.voice_clock = clock if self.is_ready() else None
        if not self.is_ready():
            return
        for guild in self.guilds:
            try:
                await self.maintain_guild(guild, now, elapsed, clock)
            except Exception:
                log.exception("Hintergrundprüfung fehlgeschlagen (Server %s); nächster Versuch folgt.", guild.id)

    async def maintain_guild(self, guild, now, elapsed, clock):
        c = self.service.settings(guild.id)
        await self.flush_moderation(guild)
        await self.flush_events(guild)
        await self.repair_event_links(guild)
        if c["voice_enabled"] and "activity" in c["features"] and elapsed:
            for channel in guild.voice_channels + guild.stage_channels:
                if channel == guild.afk_channel:
                    continue
                members = [m for m in channel.members if not m.bot and m.voice and not any((m.voice.self_mute, m.voice.self_deaf, m.voice.mute, m.voice.deaf, m.voice.suppress))]
                if len(members) < c.get("voice_minimum_members", 1):
                    continue
                for member in members:
                    before = self.service.store.stats(guild.id, member.id)["voice_seconds"]
                    xp = ((before + elapsed) // 60 - before // 60) * c["voice_xp_per_minute"]
                    self.service.store.voice(guild.id, member.id, elapsed, xp)
                    await self.sync_roles(member, c)
        birthday_channel = await self.resolve_channel(guild, int(c["channels"]["birthdays"] or 0))
        if isinstance(birthday_channel, (discord.TextChannel, discord.Thread)):
            for user, delivery in self.service.due_birthdays(guild.id, now):
                if guild.get_member(user) is None:
                    continue
                text = self.service.style(f"Alles Gute zum Geburtstag, <@{user}>! Schön, dass du Teil unserer Community bist.",
                                          f"<@{user}>, ein weiteres Jahr überstanden. Herzlichen Glückwunsch zum erfolgreichen Systembetrieb.")
                template = c.get("messages", {}).get("birthday")
                if template:
                    text = template.format(name=guild.get_member(user).display_name, user_id=user, server=guild.name, member_count=guild.member_count or 0)
                # Allow exactly the birthday user's mention, never roles/everyone.
                kwargs = {}
                try:
                    text = discord.utils.escape_mentions(text)
                    if template:
                        text = f"<@{user}> " + text
                    birthday_member = guild.get_member(user)
                    reply = Reply("🎂 Alles Gute zum Geburtstag!", text, fields=[("🎉 Ein Tag für dich", "Wir wünschen dir einen schönen Geburtstag und viele gute Momente in unserer Community.", False)])
                    embed = build_embed(reply, c, birthday_member, "birthday")
                    kwargs = {}
                    birthday_style = c.get("embed_templates", {}).get("birthday", {})
                    if not birthday_style.get("image_url") and birthday_style.get("use_default_banner", "image_url" not in birthday_style) and birthday_channel.permissions_for(guild.me).attach_files:
                        avatar = None
                        if isinstance(getattr(birthday_member, "display_avatar", None), discord.Asset):
                            try:
                                avatar = await birthday_member.display_avatar.with_size(256).with_format("png").read()
                            except discord.HTTPException:
                                pass
                        card = await asyncio.to_thread(render_card, "birthday", name=birthday_member.display_name, server=guild.name, style=birthday_style.get("image_style", {}), avatar_bytes=avatar if isinstance(avatar, bytes) else None)
                        kwargs["file"] = discord.File(BytesIO(card), filename="birthday.png")
                        embed.set_image(url="attachment://birthday.png")
                    sent = await birthday_channel.send(content=f"<@{user}>", embed=embed, **kwargs, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, replied_user=False, users=[discord.Object(id=user)]))
                    self.index.record(sent, "birthdays", metadata={"title": reply.title})
                    self.service.store.mark(guild.id, delivery)
                except discord.HTTPException as exc:
                    log.warning("Geburtstagsmeldung fehlgeschlagen (%s).", type(exc).__name__)
                finally:
                    if "file" in kwargs:
                        kwargs["file"].close()
                        kwargs["file"].fp.close()
        if "notifications" not in c["features"]:
            return
        normal_due = clock >= self.next_poll.get(guild.id, 0)
        if normal_due:
            self.next_poll[guild.id] = clock + c["poll_seconds"]
        for source in c["sources"]:
            if source.get("enabled", True) is False:
                continue
            variants = [("videos" if source["platform"] == "youtube" else source["platform"], False)]
            if source["platform"] == "youtube" and source.get("livestreams"):
                variants.append(("youtube_streams", True))
            for channel_key, live in variants:
                next_due = self.notifications.next_due(guild.id, source, live=live) if hasattr(self.notifications, "next_due") else None
                pending_due = next_due is not None and time.time() >= next_due
                if not normal_due and not pending_due:
                    continue
                live_key = guild.id, source["account"]
                if live and clock < self.next_live_poll.get(live_key, 0) and not pending_due:
                    continue
                channel_id = source.get("channel_id") or c["channels"].get(channel_key) or (c["channels"].get("streams") if channel_key in {"twitch", "youtube_streams"} else 0)
                channel = await self.resolve_channel(guild, int(channel_id or 0))
                if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                    continue
                if live:
                    self.next_live_poll[live_key] = clock + c.get("live_poll_seconds", 1800)
                async def send(platform, account, item):
                    title = ("YouTube-Livestream gestartet" if platform == "youtube" else "Twitch-Livestream gestartet") if item.kind == "live" else ("Neues TikTok-Video" if platform == "tiktok" else "Neues YouTube-Video")
                    reply = Reply(title, discord.utils.escape_markdown(item.title), fields=[("🎬 Creator", discord.utils.escape_mentions(item.creator or account)[:150], False)])
                    key = "notify_youtube_live" if platform == "youtube" and item.kind == "live" else "notify_" + platform
                    embed = build_embed(reply, c, template_key=key)
                    embed.url = item.url
                    if item.thumbnail_url and not c.get("embed_templates", {}).get(key, {}).get("image_url"):
                        embed.set_image(url=item.thumbnail_url)
                    view = discord.ui.View(timeout=None)
                    view.add_item(discord.ui.Button(label="Livestream ansehen" if item.kind == "live" else "Video ansehen", emoji="▶️", url=item.url))
                    sent = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                    self.index.record(sent, channel_key, metadata={"title": title, "content_url": item.url})
                try:
                    await self.notifications.poll(guild.id, source, send, live=live, delay_seconds=c.get("stream_delay_seconds", 0))
                except Exception as exc:
                    # Do not include request bodies/headers or API keys in logs.
                    log.warning("Inhaltsquelle %s/%s momentan nicht verfügbar (%s).", source["platform"], source["account"], type(exc).__name__)

    @maintenance.before_loop
    async def wait_ready(self):
        await self.wait_until_ready()
