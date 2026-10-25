"""Machine-local dashboard state. No bot tokens enter this database."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from .dashboard_auth import DashboardAuth, AuthorizationError, authorize_action

OWNER_ID = 965593518745731152


def control_path():
    folder = Path(os.environ.get("DCBOTS_DASHBOARD_DIR", str(Path.home() / ".mittelkap" / "dcbots" / "dashboard")))
    if not folder.is_absolute():
        raise ValueError("Dashboard-Ablage muss ein absoluter Pfad sein.")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "control.sqlite"


def wire(value):
    """Discord snowflakes must not be rounded by JavaScript."""
    if isinstance(value, dict):
        return {str(k): wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    return value


class ControlBus:
    def __init__(self, path=None):
        self.db = sqlite3.connect(str(path or control_path()), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS dashboard_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dashboard_sessions (id TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS dashboard_attempts (address TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS dashboard_snapshots (bot TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dashboard_actions (
          id TEXT PRIMARY KEY, bot TEXT NOT NULL, guild TEXT NOT NULL, kind TEXT NOT NULL,
          payload TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', result TEXT, request_key TEXT UNIQUE NOT NULL);
        """)
        self.auth = DashboardAuth(self.db)

    def close(self):
        self.db.close()

    def meta(self, key):
        row = self.db.execute("SELECT value FROM dashboard_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def publish(self, bot, payload):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO dashboard_snapshots VALUES (?,?,?)", (bot, time.time(), json.dumps(wire(payload), ensure_ascii=False)))

    def snapshots(self):
        return [{"bot": r["bot"], "updated": r["updated"], **json.loads(r["payload"])} for r in self.db.execute("SELECT * FROM dashboard_snapshots ORDER BY bot")]

    def enqueue(self, bot, guild, kind, payload, request_key, *, actor_id=None, actor_version=None):
        actor = self.auth.get(actor_id) if actor_id else None
        if actor_id:
            if not actor or not actor["enabled"] or actor["auth_version"] != actor_version:
                raise AuthorizationError("Das Webkonto wurde geändert. Bitte erneut anmelden.")
            authorize_action(actor, kind, payload)
        identity = uuid.uuid4().hex
        now = time.time()
        with self.db:
            inserted = self.db.execute("INSERT OR IGNORE INTO dashboard_actions(id,bot,guild,kind,payload,created,updated,request_key,actor_id,actor_version,actor_username) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (identity, bot, str(guild), kind, json.dumps(payload), now, now, request_key, actor_id, actor_version or 0, actor["username"] if actor else None)).rowcount
        row = self.db.execute("SELECT * FROM dashboard_actions WHERE request_key=?", (request_key,)).fetchone()
        if (row["bot"], row["guild"], row["kind"], json.loads(row["payload"]), row["actor_id"]) != (bot, str(guild), kind, payload, actor_id):
            raise ValueError("Diese Anfragekennung wurde bereits für andere Daten verwendet.")
        if inserted:
            self.auth.audit(actor, "action_enqueued", row["id"], {"bot": bot, "guild": str(guild), "kind": kind})
        return row["id"]

    def authorize_queued(self, action):
        actor = self.auth.get(action.get("actor_id"))
        if not actor or not actor["enabled"] or actor["auth_version"] != action.get("actor_version"):
            raise AuthorizationError("Auftrag verworfen: Das Webkonto oder seine Rechte wurden seit der Beauftragung geändert.")
        authorize_action(actor, action["kind"], action["payload"])
        return actor

    def claim(self, bot):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("UPDATE dashboard_actions SET status='expired',result=?,updated=? WHERE status='pending' AND created<?",
                            (json.dumps({"text": "Auftrag abgelaufen. Bot war nicht rechtzeitig verfügbar."}), time.time(), time.time()-300))
            row = self.db.execute("SELECT * FROM dashboard_actions WHERE bot=? AND status='pending' ORDER BY created LIMIT 1", (bot,)).fetchone()
            if row:
                self.db.execute("UPDATE dashboard_actions SET status='running',updated=? WHERE id=?", (time.time(), row["id"]))
                return {**dict(row), "payload": json.loads(row["payload"])}

    def recover(self, bot):
        # Never replay moderation after a crash with an ambiguous result.
        with self.db:
            self.db.execute("UPDATE dashboard_actions SET status='unknown',result=?,updated=? WHERE bot=? AND status='running'",
                            (json.dumps({"text": "Bot wurde während der Bearbeitung beendet. Serverzustand prüfen; keine automatische Wiederholung."}), time.time(), bot))

    def finish(self, identity, result, status="done"):
        row = self.db.execute("SELECT actor_id,actor_username FROM dashboard_actions WHERE id=?", (identity,)).fetchone()
        with self.db:
            self.db.execute("UPDATE dashboard_actions SET status=?,result=?,updated=? WHERE id=?", (status, json.dumps(wire(result)), time.time(), identity))
        if row:
            self.auth.audit({"id": row["actor_id"], "username": row["actor_username"]}, "action_" + status, identity)

    def action(self, identity):
        row = self.db.execute("SELECT id,bot,guild,kind,status,result,created,updated,actor_id,actor_username FROM dashboard_actions WHERE id=?", (identity,)).fetchone()
        return {**dict(row), "result": json.loads(row["result"]) if row["result"] else None} if row else None
