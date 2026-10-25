"""Persistent, server-scoped XP adjustments and non-stacking timed boosts."""
from __future__ import annotations

import json
import math
import time


class XPAdmin:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS xp_adjustments (
            guild INTEGER NOT NULL, action_id TEXT NOT NULL, actor TEXT NOT NULL,
            operation TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL,
            changes TEXT NOT NULL, PRIMARY KEY(guild,action_id));
        CREATE TABLE IF NOT EXISTS xp_boosts (
            guild INTEGER NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, factor REAL NOT NULL,
            starts REAL NOT NULL, ends REAL NOT NULL, scope TEXT NOT NULL, targets TEXT NOT NULL,
            reason TEXT NOT NULL, actor TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(guild,id));
        """)

    @staticmethod
    def reason(payload):
        value = payload.get("reason")
        if not isinstance(value, str) or not 3 <= len(value.strip()) <= 300:
            raise ValueError("Bitte einen nachvollziehbaren Grund mit 3–300 Zeichen angeben.")
        return value.strip()

    @staticmethod
    def target_spec(payload):
        scope, raw = payload.get("scope"), payload.get("targets", [])
        if scope not in {"members", "roles", "all"} or not isinstance(raw, list):
            raise ValueError("Bitte Mitglieder, Rollen oder den gesamten Server auswählen.")
        if len(raw) > 10000 or any(not str(v).isdigit() or not 0 < int(v) < 2**63 for v in raw):
            raise ValueError("Die Auswahl enthält ungültige IDs.")
        targets = sorted(set(int(v) for v in raw)) if scope != "all" else []
        if scope != "all" and not targets:
            raise ValueError("Bitte mindestens ein Mitglied beziehungsweise eine Rolle auswählen.")
        return scope, targets

    @staticmethod
    def select_members(guild, scope, targets):
        if scope == "roles" and any(guild.get_role(t) is None for t in targets):
            raise ValueError("Eine ausgewählte Rolle existiert auf diesem Server nicht mehr.")
        if scope == "members" and any(guild.get_member(t) is None for t in targets):
            raise ValueError("Ein ausgewähltes Mitglied ist nicht mehr auf diesem Server. Bitte aktualisieren.")
        return [m for m in guild.members if not m.bot and (
            scope == "all" or scope == "members" and m.id in targets or
            scope == "roles" and any(r.id in targets for r in m.roles))]

    def adjust(self, guild, action_id, members, payload, actor, now=None):
        reason = self.reason(payload)
        op, amount = payload.get("operation"), payload.get("amount")
        if op not in {"add", "remove", "set"} or type(amount) is not int or not 0 <= amount <= 10**9:
            raise ValueError("Bitte addieren, abziehen oder setzen und eine ganze XP-Zahl von 0 bis 1.000.000.000 wählen.")
        # One transaction covers the entire selection and its durable replay guard.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            previous = self.db.execute("SELECT changes FROM xp_adjustments WHERE guild=? AND action_id=?", (guild, action_id)).fetchone()
            if previous:
                return json.loads(previous[0])
            changes = []
            for member in {m.id: m for m in members}.values():
                if member.bot:
                    continue
                self.db.execute("INSERT OR IGNORE INTO activity(guild,user) VALUES (?,?)", (guild, member.id))
                before = self.db.execute("SELECT xp FROM activity WHERE guild=? AND user=?", (guild, member.id)).fetchone()[0]
                after = amount if op == "set" else max(0, before + (amount if op == "add" else -amount))
                if after > 10**12:
                    raise ValueError("Die Änderung würde den unterstützten XP-Gesamtstand überschreiten.")
                self.db.execute("UPDATE activity SET xp=? WHERE guild=? AND user=?", (after, guild, member.id))
                changes.append({"id": str(member.id), "name": member.display_name, "before": before, "after": after})
            if not changes:
                raise ValueError("Die Auswahl enthält keine menschlichen Mitglieder. Es wurde nichts geändert.")
            self.db.execute("INSERT INTO xp_adjustments VALUES (?,?,?,?,?,?,?)", (guild, action_id, actor, op, reason, now if now is not None else time.time(), json.dumps(changes)))
        return changes

    def create_boost(self, guild, action_id, payload, actor, now=None):
        now = time.time() if now is None else now
        reason = self.reason(payload)
        scope, targets = self.target_spec(payload)
        factor, starts, ends = payload.get("factor"), payload.get("starts", now), payload.get("ends")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (factor, starts, ends)):
            raise ValueError("Faktor und Start-/Endzeit müssen gültige Zahlen sein.")
        if not 1 < factor <= 10 or not now - 120 <= starts <= now + 366*86400 or not max(now, starts) < ends <= starts + 366*86400:
            raise ValueError("Booster: Faktor größer als 1 bis 10, Start ab jetzt und Dauer höchstens 366 Tage.")
        name = payload.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Bitte einen Eventnamen mit 1–80 Zeichen angeben.")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO xp_boosts VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                            (guild, action_id, name.strip(), factor, starts, ends, scope, json.dumps(targets), reason, actor))

    def cancel(self, guild, boost_id):
        with self.db:
            if not self.db.execute("UPDATE xp_boosts SET cancelled=1 WHERE guild=? AND id=?", (guild, boost_id)).rowcount:
                raise ValueError("Dieser Booster gehört nicht zu diesem Server oder existiert nicht.")

    def multiplier(self, guild, member, now=None):
        now = time.time() if now is None else now
        roles = {r.id for r in member.roles}
        factor = 1.0
        for row in self.db.execute("SELECT * FROM xp_boosts WHERE guild=? AND cancelled=0 AND starts<=? AND ends>?", (guild, now, now)):
            targets = set(json.loads(row["targets"]))
            if row["scope"] == "all" or row["scope"] == "members" and member.id in targets or row["scope"] == "roles" and roles.intersection(targets):
                factor = max(factor, row["factor"])
        return factor

    def snapshot(self, guild):
        boosts = []
        for r in self.db.execute("SELECT * FROM xp_boosts WHERE guild=? ORDER BY cancelled,ends DESC LIMIT 100", (guild,)):
            row = dict(r)
            row["targets"] = [str(v) for v in json.loads(row["targets"])]
            row["guild"] = str(row["guild"])
            boosts.append(row)
        adjustments = []
        for r in self.db.execute("SELECT * FROM xp_adjustments WHERE guild=? ORDER BY created DESC LIMIT 30", (guild,)):
            row = dict(r)
            changes = json.loads(row.pop("changes"))
            row.update(guild=str(guild), count=len(changes), delta=sum(x["after"]-x["before"] for x in changes), changes=changes[:20])
            adjustments.append(row)
        return {"boosts": boosts, "adjustments": adjustments}


async def execute_xp(bridge, action, account, guild):
    client, payload = bridge.client, action["payload"]
    if bridge.bot != "jarvis":
        raise ValueError("Aktivität und Rangkarte gehören zu Jarvis. Bitte oben Jarvis auswählen.")
    if payload.get("confirm") is not True:
        raise ValueError("XP-Änderungen müssen ausdrücklich bestätigt werden.")
    xp = client.xp
    op = payload.get("operation")
    if op == "cancel_boost":
        bridge.bus.authorize_queued(action)
        xp.cancel(guild.id, str(payload.get("boost_id", "")))
        return {"text": "Booster beendet. Bereits verdiente XP bleiben erhalten."}
    scope, targets = xp.target_spec(payload)
    # Never silently grant to only the cached subset of a role/server.
    if not guild.chunked:
        import asyncio
        await asyncio.wait_for(guild.chunk(cache=True), 90)
    if not guild.chunked:
        raise ValueError("Das Mitgliederverzeichnis ist noch unvollständig. Bitte später erneut versuchen.")
    members = xp.select_members(guild, scope, targets)
    bridge.bus.authorize_queued(action)
    actor = account["display_name"] + " (" + account["username"] + ")"
    if op == "boost":
        xp.create_boost(guild.id, action["id"], payload, actor)
        return {"text": "XP-Booster gespeichert. Er beginnt und endet automatisch zur gewählten Zeit; der höchste passende Faktor zählt."}
    changes = xp.adjust(guild.id, action["id"], members, payload, actor)
    role_failures = 0
    for member in members:
        try:
            await client.sync_roles(member, client.service.settings(guild.id))
        except Exception:
            role_failures += 1
    return {"text": f"XP für {len(changes)} Mitglieder geändert. Verlauf gespeichert. " +
            (f"Rollen konnten bei {role_failures} Mitgliedern noch nicht abgeglichen werden." if role_failures else "Erreichte Belohnungsrollen wurden geprüft."), "count": len(changes)}
