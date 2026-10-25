from __future__ import annotations

import sqlite3
import json
from pathlib import Path


def level_for(xp: int) -> int:
    from math import isqrt
    return isqrt(max(0, xp) // 100)


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS activity (
            guild INTEGER NOT NULL, user INTEGER NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
            messages INTEGER NOT NULL DEFAULT 0, voice_seconds INTEGER NOT NULL DEFAULT 0,
            last_text_xp REAL, PRIMARY KEY (guild, user));
        CREATE TABLE IF NOT EXISTS birthdays (
            guild INTEGER NOT NULL, user INTEGER NOT NULL, day INTEGER NOT NULL, month INTEGER NOT NULL,
            PRIMARY KEY (guild, user));
        CREATE TABLE IF NOT EXISTS settings (guild INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS delivered (guild INTEGER NOT NULL, key TEXT NOT NULL,
            PRIMARY KEY (guild, key));
        CREATE TABLE IF NOT EXISTS state (guild INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (guild, key));
        CREATE TABLE IF NOT EXISTS moderation (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER NOT NULL, message INTEGER NOT NULL,
            actor INTEGER NOT NULL, target INTEGER NOT NULL, action TEXT NOT NULL, duration INTEGER,
            reason TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
            log_delivered INTEGER NOT NULL DEFAULT 0, UNIQUE(guild,message));
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER NOT NULL,
            event_key TEXT, title TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL,
            delivered INTEGER NOT NULL DEFAULT 0, UNIQUE(guild,event_key));
        CREATE TABLE IF NOT EXISTS activity_events (guild INTEGER NOT NULL, event_key TEXT NOT NULL,
            PRIMARY KEY(guild,event_key));
        """)
        for table, name, declaration in (("activity", "voice_message_seconds", "INTEGER NOT NULL DEFAULT 0"),
                                         ("activity", "voice_messages", "INTEGER NOT NULL DEFAULT 0"),
                                         ("moderation", "metadata", "TEXT NOT NULL DEFAULT '{}'")):
            if name not in {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
        self.db.commit()

    def close(self):
        self.db.close()

    def settings(self, guild: int) -> dict:
        row = self.db.execute("SELECT value FROM settings WHERE guild=?", (guild,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_settings(self, guild: int, value: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (guild, json.dumps(value)))

    def stats(self, guild: int, user: int) -> dict:
        row = self.db.execute("SELECT * FROM activity WHERE guild=? AND user=?", (guild, user)).fetchone()
        result = dict(row) if row else {"xp": 0, "messages": 0, "voice_seconds": 0, "voice_message_seconds": 0, "voice_messages": 0}
        result["level"] = level_for(result["xp"])
        result["rank"] = 1 + self.db.execute(
            "SELECT COUNT(*) FROM activity WHERE guild=? AND xp>?", (guild, result["xp"])).fetchone()[0]
        return result

    def message(self, guild: int, user: int, now: float, xp: int, cooldown: int, eligible: bool, message_id: int | None = None) -> bool:
        with self.db:
            if message_id is not None and not self._activity_event(guild, f"message:{message_id}"):
                return False
            self.db.execute("INSERT OR IGNORE INTO activity (guild,user) VALUES (?,?)", (guild, user))
            last = self.db.execute("SELECT last_text_xp FROM activity WHERE guild=? AND user=?", (guild, user)).fetchone()[0]
            award = eligible and (last is None or now - last >= cooldown)
            self.db.execute("UPDATE activity SET messages=messages+1, xp=xp+?, last_text_xp=? WHERE guild=? AND user=?",
                            (xp if award else 0, now if award else last, guild, user))
        return award

    def _activity_event(self, guild, key):
        return self.db.execute("INSERT OR IGNORE INTO activity_events VALUES (?,?)", (guild, key)).rowcount == 1

    def voice_message(self, guild: int, user: int, message_id: int, seconds: int, xp_per_minute: int, multiplier: float = 1):
        with self.db:
            if not self._activity_event(guild, f"voice-message:{message_id}"):
                return False
            self.db.execute("INSERT OR IGNORE INTO activity (guild,user) VALUES (?,?)", (guild, user))
            before = self.db.execute("SELECT voice_message_seconds FROM activity WHERE guild=? AND user=?", (guild, user)).fetchone()[0]
            xp = ((before + seconds) * xp_per_minute // 60) - (before * xp_per_minute // 60)
            xp = int(xp * multiplier)
            self.db.execute("UPDATE activity SET voice_message_seconds=voice_message_seconds+?, voice_messages=voice_messages+1, xp=xp+? WHERE guild=? AND user=?", (seconds, xp, guild, user))
        return True

    def voice(self, guild: int, user: int, seconds: int, xp: int):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO activity (guild,user) VALUES (?,?)", (guild, user))
            self.db.execute("UPDATE activity SET voice_seconds=voice_seconds+?, xp=xp+? WHERE guild=? AND user=?",
                            (seconds, xp, guild, user))

    def birthday(self, guild: int, user: int):
        row = self.db.execute("SELECT day,month FROM birthdays WHERE guild=? AND user=?", (guild, user)).fetchone()
        return tuple(row) if row else None

    def set_birthday(self, guild: int, user: int, day: int, month: int):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO birthdays VALUES (?,?,?,?)", (guild, user, day, month))

    def delete_birthday(self, guild: int, user: int):
        with self.db:
            self.db.execute("DELETE FROM birthdays WHERE guild=? AND user=?", (guild, user))

    def birthdays(self, guild: int):
        return self.db.execute("SELECT user,day,month FROM birthdays WHERE guild=?", (guild,)).fetchall()

    def seen(self, guild: int, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM delivered WHERE guild=? AND key=?", (guild, key)).fetchone() is not None

    def mark(self, guild: int, key: str):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO delivered VALUES (?,?)", (guild, key))

    def state(self, guild: int, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE guild=? AND key=?", (guild, key)).fetchone()
        return row[0] if row else None

    def set_state(self, guild: int, key: str, value: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (guild, key, value))

    def reserve_moderation(self, guild: int, message: int, actor: int, target: int, action: str, duration: int | None, reason: str, metadata: dict | None = None):
        from datetime import datetime, timezone
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO moderation (guild,message,actor,target,action,duration,reason,created,status,metadata) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                     (guild, message, actor, target, action, duration, reason, datetime.now(timezone.utc).isoformat(), "pending", json.dumps(metadata or {})))
        row = self.db.execute("SELECT * FROM moderation WHERE guild=? AND message=?", (guild, message)).fetchone()
        return dict(row), cursor.rowcount == 1

    def finish_moderation(self, audit_id: int, status: str, error: str | None = None):
        with self.db:
            self.db.execute("UPDATE moderation SET status=?,error=? WHERE id=?", (status, error, audit_id))

    def moderation_outbox(self, guild: int):
        return [dict(r) for r in self.db.execute("SELECT * FROM moderation WHERE guild=? AND log_delivered=0 AND status!='pending' ORDER BY id LIMIT 20", (guild,))]

    def moderation_delivered(self, audit_id: int):
        with self.db:
            self.db.execute("UPDATE moderation SET log_delivered=1 WHERE id=?", (audit_id,))

    def recover_pending_moderation(self):
        # Called only after taking the live process lock, never while another action is in flight.
        with self.db:
            self.db.execute("UPDATE moderation SET status='unknown',error='ProcessRestart' WHERE status='pending'")

    def record_event(self, guild: int, title: str, text: str, event_key: str | None = None):
        from datetime import datetime, timezone
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO events (guild,event_key,title,text,created) VALUES (?,?,?,?,?)",
                            (guild, event_key, title, text, datetime.now(timezone.utc).isoformat()))

    def event_outbox(self, guild: int):
        return [dict(row) for row in self.db.execute("SELECT * FROM events WHERE guild=? AND delivered=0 ORDER BY id LIMIT 20", (guild,))]

    def event_delivered(self, event_id: int):
        with self.db:
            self.db.execute("UPDATE events SET delivered=1 WHERE id=?", (event_id,))
