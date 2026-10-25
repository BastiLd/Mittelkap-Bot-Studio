"""Durable references for bot replies and restart-safe log controls."""
from __future__ import annotations

import json
import re
import warnings
from datetime import datetime, timezone

import discord

MESSAGE_URL = re.compile(r"https://(?:www\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)")
CHANNEL_URL = re.compile(r"https://(?:www\.)?discord\.com/channels/(\d+)/(\d+)(?![\d/])")
DETAILS_ID = "dcbots:log-details:v1"


def legacy_command_name(message):
    """Old public interaction objects contain names absent from modern metadata.

    discord.py forces this one deprecation warning to 'always'. Capture only the
    synchronous legacy property access and re-emit any unrelated warnings.
    """
    with warnings.catch_warnings(record=True) as captured:
        interaction = getattr(message, "interaction", None)
    for warning in captured:
        if warning.category is DeprecationWarning and str(warning.message) == "interaction is deprecated, use interaction_metadata instead.":
            continue
        warnings.warn_explicit(warning.message, warning.category, warning.filename, warning.lineno)
    return getattr(interaction, "name", None)


class MessageIndex:
    def __init__(self, db):
        self.db = db
        db.executescript("""
        CREATE TABLE IF NOT EXISTS message_index (
          message INTEGER PRIMARY KEY, guild INTEGER NOT NULL, channel INTEGER NOT NULL,
          category TEXT NOT NULL, source_url TEXT, metadata TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS message_index_scope ON message_index(guild,category,created);
        CREATE INDEX IF NOT EXISTS message_index_event ON message_index(guild,json_extract(metadata,'$.event_id'));
        CREATE TABLE IF NOT EXISTS history_scans (
          guild INTEGER NOT NULL, category TEXT NOT NULL, channel INTEGER NOT NULL,
          examined INTEGER NOT NULL, indexed INTEGER NOT NULL, status TEXT NOT NULL,
          updated TEXT NOT NULL, PRIMARY KEY(guild,category,channel));
        CREATE TABLE IF NOT EXISTS event_context (
          guild INTEGER NOT NULL, event_key TEXT NOT NULL, metadata TEXT NOT NULL,
          PRIMARY KEY(guild,event_key));
        """)
        db.commit()

    def record(self, message, category, source_url=None, metadata=None):
        message_id = getattr(message, "id", None)
        guild = getattr(getattr(message, "guild", None), "id", None)
        channel = getattr(getattr(message, "channel", None), "id", None)
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (message_id, guild, channel)):
            return False
        if getattr(getattr(message, "flags", None), "ephemeral", False) is True:
            return False
        previous = self.get(message_id)
        if previous:
            # Startup scanning must not erase exact source data stored at send time.
            source_url = source_url or previous["source_url"]
            metadata = {**previous["metadata"], **(metadata or {})}
            category = previous["category"] if category == "history" else category
        if source_url and not MESSAGE_URL.fullmatch(source_url):
            source_url = None
        created = getattr(message, "created_at", None)
        created = created.isoformat() if isinstance(created, datetime) else datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO message_index VALUES (?,?,?,?,?,?,?)", (
                message_id, guild, channel, category, source_url, json.dumps(metadata or {}, ensure_ascii=False), created))
        return True

    def get(self, message_id):
        row = self.db.execute("SELECT * FROM message_index WHERE message=?", (message_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["metadata"] = json.loads(value["metadata"])
        return value

    def scan_status(self, guild, category, channel, examined, indexed, status):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO history_scans VALUES (?,?,?,?,?,?,?)", (
                guild, category, channel, examined, indexed, status, datetime.now(timezone.utc).isoformat()))

    def scopes(self, guild):
        return [(row[0], row[1]) for row in self.db.execute("SELECT DISTINCT category,channel FROM message_index WHERE guild=?", (guild,))]

    def channel_ids(self, guild):
        return [row[0] for row in self.db.execute("SELECT DISTINCT channel FROM message_index WHERE guild=?", (guild,))]

    def link(self, message_id, source_url, metadata=None):
        current = self.get(message_id)
        if current is None or (source_url and not MESSAGE_URL.fullmatch(source_url)):
            return
        with self.db:
            self.db.execute("UPDATE message_index SET source_url=?,metadata=? WHERE message=?", (
                source_url, json.dumps({**current["metadata"], **(metadata or {})}, ensure_ascii=False), message_id))

    def event_context(self, guild, event_key, value=None):
        if not event_key:
            return {}
        if value is not None:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO event_context VALUES (?,?,?)", (guild, event_key, json.dumps(value)))
        row = self.db.execute("SELECT metadata FROM event_context WHERE guild=? AND event_key=?", (guild, event_key)).fetchone()
        return json.loads(row[0]) if row else {}


class EventReferences:
    """Shared cross-bot ledger, stored in the private dashboard ControlBus DB."""
    def __init__(self, db):
        self.db = db
        db.executescript("""
        CREATE TABLE IF NOT EXISTS event_references (
          message INTEGER PRIMARY KEY, guild INTEGER NOT NULL, channel INTEGER NOT NULL,
          user INTEGER NOT NULL, event TEXT NOT NULL, kind TEXT NOT NULL,
          membership TEXT NOT NULL, event_time REAL NOT NULL, bot TEXT NOT NULL,
          source_message INTEGER, deleted INTEGER NOT NULL DEFAULT 0, source_deleted INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS event_reference_match ON event_references(guild,user,event,kind,event_time);
        """)
        db.commit()

    def record(self, message, context, kind, bot):
        mid, gid, cid = getattr(message, "id", None), getattr(getattr(message, "guild", None), "id", None), getattr(getattr(message, "channel", None), "id", None)
        if not all(type(value) is int for value in (mid, gid, cid)) or context.get("member_event") not in {"join", "leave"}:
            return False
        with self.db:
            self.db.execute("""INSERT INTO event_references(message,guild,channel,user,event,kind,membership,event_time,bot)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(message) DO UPDATE SET
                membership=CASE WHEN excluded.membership!='' THEN excluded.membership ELSE event_references.membership END,
                event_time=excluded.event_time,deleted=0""", (mid, gid, cid, int(context["member_id"]), context["member_event"], kind,
                    context.get("membership", ""), float(context["event_time"]), bot))
        return True

    def get(self, message):
        row = self.db.execute("SELECT * FROM event_references WHERE message=?", (message,)).fetchone()
        return dict(row) if row else None

    def match(self, context, guild, log_message=None):
        user, event = int(context["member_id"]), context["member_event"]
        membership = context.get("membership", "")
        if membership:
            rows = self.db.execute("SELECT * FROM event_references WHERE guild=? AND user=? AND event=? AND kind='announcement' AND membership=?", (guild,user,event,membership)).fetchall()
            if rows:
                return dict(rows[0]) if len(rows) == 1 else None
        # Historical records have no membership key. A strict time window and
        # bidirectional uniqueness prevent guessing during fast rejoin cycles.
        moment = float(context["event_time"])
        rows = self.db.execute("SELECT * FROM event_references WHERE guild=? AND user=? AND event=? AND kind='announcement' AND ABS(event_time-?)<=60 AND (?='' OR membership='' OR membership=?)", (guild,user,event,moment,membership,membership)).fetchall()
        if len(rows) != 1:
            return None
        candidate = rows[0]
        peers = self.db.execute("SELECT message FROM event_references WHERE guild=? AND user=? AND event=? AND kind='log' AND ABS(event_time-?)<=60", (guild,user,event,candidate["event_time"])).fetchall()
        if len(peers) > 1 or (len(peers) == 1 and log_message is not None and peers[0][0] != log_message):
            return None
        return dict(candidate)

    def pending(self, guild, bot):
        return [dict(row) for row in self.db.execute("""SELECT logs.* FROM event_references logs
          LEFT JOIN event_references source ON logs.source_message=source.message
          WHERE logs.guild=? AND logs.bot=? AND logs.kind='log' AND logs.deleted=0
            AND (logs.source_message IS NULL OR COALESCE(source.deleted,0)!=logs.source_deleted)
          ORDER BY logs.event_time DESC""", (guild,bot))]

    def bind(self, message, source):
        with self.db:
            self.db.execute("UPDATE event_references SET source_message=?,source_deleted=? WHERE message=?", (source["message"],source["deleted"],message))

    def mark_deleted(self, message):
        with self.db:
            self.db.execute("UPDATE event_references SET deleted=1 WHERE message=?", (message,))

    def mark_missing(self, guild, channel, bot, seen, oldest, newest):
        """Only a successfully scanned interval proves an announcement missing."""
        rows = self.db.execute("SELECT message FROM event_references WHERE guild=? AND channel=? AND bot=? AND kind='announcement' AND message BETWEEN ? AND ?", (guild,channel,bot,oldest,newest)).fetchall()
        with self.db:
            for row in rows:
                if row[0] not in seen:
                    self.db.execute("UPDATE event_references SET deleted=1 WHERE message=?", (row[0],))


def member_context(message, category, previous=None):
    """Recover only explicit member IDs and recognized member-event messages."""
    saved = (previous or {}).get("metadata", {})
    if saved.get("member_event") in {"join", "leave"} and saved.get("member_id"):
        return saved
    embeds = getattr(message, "embeds", [])
    if not embeds:
        return None
    title = (embeds[0].title or "").casefold()
    event = {"welcome": "join", "farewell": "leave"}.get(category)
    if category == "logs":
        # Strip decorative leading symbols without accepting arbitrary substrings.
        normalized = title.lstrip(" 👋🚪📋✦✅🟢🔴➕➖")
        event = "join" if normalized == "mitglied beigetreten" else ("leave" if normalized == "mitglied ausgetreten" else None)
    elif category == "welcome" and "willkommen" not in title:
        return None
    elif category == "farewell" and not any(word in title for word in ("verlassen", "abschied", "tschüss", "verbindung getrennt")):
        return None
    if event is None:
        return None
    text = (embeds[0].description or "").replace("**", "")
    ids = set(re.findall(r"(?m)^(?:👤 )?Mitglied: (\d{1,20})(?:\s|$)", text))
    for field in embeds[0].fields:
        if field.name in {"👤 Mitglied", "Mitglied", "Betroffenes Mitglied"}:
            ids.update(re.findall(r"`(\d{1,20})`|https://discord\.com/users/(\d{1,20})", field.value))
    # Flatten alternate regex capture groups, while requiring one unique ID.
    ids = {str(value) if not isinstance(value, tuple) else next((v for v in value if v), "") for value in ids}
    ids.discard("")
    if len(ids) != 1 or not 0 < int(next(iter(ids))) < 2**63:
        return None
    timestamp = embeds[0].timestamp or getattr(message, "created_at", None)
    if not isinstance(timestamp, datetime):
        return None
    return {"member_event": event, "member_id": int(next(iter(ids))), "membership": "", "event_time": timestamp.timestamp()}


def references(reply, guild_id=None):
    # Message content may itself quote other Discord URLs. The header's IDs are
    # authoritative; never treat an arbitrary URL in the logged body as origin.
    plain = reply.text.replace("**", "").replace("💬 ", "")
    identity = re.search(r"(?m)^Kanal: <#(\d+)> · Nachricht: (\d+)", plain)
    source_url = f"https://discord.com/channels/{guild_id}/{identity[1]}/{identity[2]}" if identity and guild_id else None
    if not source_url:
        labelled = re.search(r"(?m)^Ehemaliger Nachrichtenverweis: (https://(?:www\.)?discord\.com/channels/\d+/\d+/\d+)", plain)
        if not labelled:
            labelled = re.search(r"\[Nachricht öffnen\]\((https://(?:www\.)?discord\.com/channels/\d+/\d+/\d+)\)", plain)
        source_url = labelled[1] if labelled else None
    for name, value, _ in reply.fields:
        if not source_url and name in {"Aufrufkanal", "Ursprüngliche Nachricht", "Nachricht", "Willkommensnachricht", "Abschiedsnachricht"}:
            match = MESSAGE_URL.search(str(value))
            source_url = match[0] if match else None
    source = MESSAGE_URL.fullmatch(source_url) if source_url else None
    if source:
        channel_url = f"https://discord.com/channels/{source[1]}/{source[2]}"
    else:
        channel = CHANNEL_URL.search(plain)
        channel_url = channel[0] if channel else None
    return source_url, channel_url


class LogDetailsView(discord.ui.View):
    def __init__(self, client, source_url=None, channel_url=None, deleted=False):
        super().__init__(timeout=None)
        self.client = client
        if source_url and not deleted:
            self.add_item(discord.ui.Button(label="Zur Nachricht", emoji="🔗", url=source_url))
        if channel_url:
            self.add_item(discord.ui.Button(label="Kanal öffnen", emoji="💬", url=channel_url))

    @discord.ui.button(label="Details & Verweis", emoji="📋", style=discord.ButtonStyle.secondary, custom_id=DETAILS_ID)
    async def details(self, interaction: discord.Interaction, button):
        if not interaction.guild or not interaction.message:
            await interaction.response.send_message("Dieser Verweis gehört zu einem Serverprotokoll.", ephemeral=True)
            return
        record = self.client.index.get(interaction.message.id)
        if not record or record["guild"] != interaction.guild_id:
            await interaction.response.send_message("Für diese Nachricht ist noch kein genauer Verweis gespeichert. Die Verwaltung kann den Verlauf über /einstellungen erneut einlesen.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            viewer = await interaction.guild.fetch_member(interaction.user.id)
            channel = await self.client.resolve_channel(interaction.guild, record["channel"])
            if channel is None or not channel.permissions_for(viewer).view_channel:
                await interaction.followup.send("Du hast keinen Zugriff auf diesen Protokollkanal.", ephemeral=True)
                return
            metadata = record["metadata"]
            embed = discord.Embed(title="📋 Gespeicherter Protokollverweis", color=0x8B8CF8)
            embed.add_field(name="Protokoll", value=f"[Diese Meldung öffnen](https://discord.com/channels/{record['guild']}/{record['channel']}/{record['message']})", inline=False)
            source = record["source_url"]
            event_refs = getattr(self.client, "event_refs", None)
            shared_log = event_refs.get(record["message"]) if event_refs else None
            shared_source = event_refs.get(shared_log["source_message"]) if shared_log and shared_log["source_message"] else None
            source_deleted = metadata.get("deleted") or metadata.get("source_deleted") or (shared_source and shared_source["deleted"])
            label = ("Willkommensnachricht" if metadata.get("member_event") == "join" else "Abschiedsnachricht") if metadata.get("member_event") else "Ursprüngliche Nachricht"
            if source:
                match = MESSAGE_URL.fullmatch(source)
                origin = await self.client.resolve_channel(interaction.guild, int(match[2])) if match and int(match[1]) == interaction.guild_id else None
                if origin and origin.permissions_for(viewer).view_channel and origin.permissions_for(viewer).read_message_history:
                    if not source_deleted and metadata.get("member_event"):
                        try:
                            await origin.fetch_message(int(match[3]))
                        except discord.NotFound:
                            source_deleted = True
                            if event_refs:
                                event_refs.mark_deleted(int(match[3]))
                            self.client.index.link(record["message"], source, {"source_deleted": True})
                    if source_deleted:
                        embed.add_field(name=label, value="Die zugehörige Nachricht wurde gelöscht. Ihr ehemaliger Verweis ist dokumentiert, kann aber keine gelöschte Nachricht wiederherstellen.\n" + source, inline=False)
                    else:
                        embed.add_field(name=label, value=f"[Genau diese Nachricht öffnen]({source})", inline=False)
                else:
                    embed.add_field(name=label, value="Der Ursprungskanal ist nicht mehr vorhanden oder für dich nicht zugänglich.", inline=False)
            else:
                embed.add_field(name=label, value="Noch keine eindeutig zugeordnete Willkommens- oder Abschiedsnachricht gefunden." if metadata.get("member_event") else "Für dieses Ereignis existiert kein genauer Nachrichtenverweis (z. B. Rollenänderung oder privater Slash-Aufruf).", inline=False)
            embed.add_field(name="Kategorie", value=metadata.get("title", record["category"])[:256], inline=True)
            embed.set_footer(text="Verweis dauerhaft gespeichert • bleibt nach einem Neustart erhalten")
            await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await interaction.followup.send("Discord konnte die Zugriffsrechte gerade nicht bestätigen. Bitte erneut versuchen.", ephemeral=True)
