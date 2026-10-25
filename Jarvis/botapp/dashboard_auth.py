"""Local web identities and the same authorization rules at HTTP and bot execution."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

OWNER_ACCOUNT_ID = "owner"
DEFAULT_PREFERENCES = {"identity_order": "name", "theme": "retro", "reduced_motion": False}
PERMISSION_CATALOG = [
    ("view.overview", "Übersicht und Botstatus ansehen", "Lesen"),
    ("view.analytics", "Statistiken und Rangliste ansehen", "Lesen"),
    ("view.logs", "Server- und Moderationsprotokolle ansehen", "Lesen"),
    ("view.members", "Mitglieder und Rollen ansehen", "Lesen"),
    ("view.settings", "Alle Bot-Einstellungen ansehen", "Lesen"),
    ("edit.channels", "Ausgabekanäle ändern", "Bearbeiten"),
    ("edit.links", "Profillinks ändern", "Bearbeiten"),
    ("edit.sources", "Inhaltsquellen und Stream-Verzögerung ändern", "Bearbeiten"),
    ("edit.activity", "Aktivität und XP einstellen", "Bearbeiten"),
    ("edit.birthdays", "Geburtstagszeit und Zeitzone einstellen", "Bearbeiten"),
    ("edit.commands", "Befehle und Sichtbarkeit bearbeiten", "Bearbeiten"),
    ("edit.embeds", "Texte, Embeds und Karten gestalten", "Bearbeiten"),
    ("edit.general", "Allgemeine Botfunktionen einstellen", "Bearbeiten"),
    ("edit.roles", "Belohnungsrollen verwalten", "Bearbeiten"),
    ("run.scan", "Nachrichtenindex einstellen und neu einlesen", "Ausführen"),
    ("run.sync", "Slash-Befehle mit Discord synchronisieren", "Ausführen"),
    ("send.messages", "Botnachrichten veröffentlichen", "Ausführen"),
    ("moderate.ban", "Mitglieder bannen", "Moderation"),
    ("moderate.unban", "Serversperren aufheben", "Moderation"),
    ("moderate.timeout", "Mitglieder stummschalten", "Moderation"),
    ("moderate.kick", "Mitglieder vom Server entfernen", "Moderation"),
    ("moderate.untimeout", "Stummschaltungen aufheben", "Moderation"),
    ("moderate.reinvite", "Mitglieder erneut einladen", "Moderation"),
    ("users.create", "Normale Webkonten anlegen", "Webkonten verwalten"),
    ("users.edit", "Anzeigenamen normaler Webkonten ändern", "Webkonten verwalten"),
    ("users.password", "Passwörter normaler Webkonten zurücksetzen", "Webkonten verwalten"),
    ("users.permissions", "Eigene Funktionsrechte an normale Webkonten vergeben", "Webkonten verwalten"),
    ("users.disable", "Normale Webkonten sperren und freischalten", "Webkonten verwalten"),
]
PERMISSIONS = {key for key, _, _ in PERMISSION_CATALOG}
USER_PERMISSIONS = {key for key in PERMISSIONS if key.startswith("users.")}
MODERATION_PERMISSIONS = {key for key in PERMISSIONS if key.startswith("moderate.")}
SETTING_PERMISSIONS = {
    "channels": "edit.channels", "links": "edit.links", "sources": "edit.sources",
    "stream_delay_seconds": "edit.sources", "poll_seconds": "edit.sources", "live_poll_seconds": "edit.sources",
    "text_xp": "edit.activity", "minimum_message_length": "edit.activity", "text_cooldown_seconds": "edit.activity",
    "voice_enabled": "edit.activity", "voice_xp_per_minute": "edit.activity", "voice_message_xp_per_minute": "edit.activity", "voice_minimum_members": "edit.activity",
    "birthday_time": "edit.birthdays", "timezone": "edit.birthdays", "leap_day": "edit.birthdays",
    "command_settings": "edit.commands", "messages": "edit.embeds", "embed_templates": "edit.embeds", "color": "edit.embeds",
    "creator_name": "edit.general", "features": "edit.general", "log_message_content": "edit.general",
    "level_roles": "edit.roles", "history_scan_limit": "run.scan", "history_scan_overrides": "run.scan",
}
OWNER_SETTINGS = {"admin_role_ids", "moderator_role_ids", "protected_role_ids"}


class AuthorizationError(ValueError):
    pass


def catalog():
    return [{"id": key, "label": label, "group": group} for key, label, group in PERMISSION_CATALOG]


def hash_password(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32).hex()


def password_record(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Bitte ein Passwort mit 12 bis 256 Zeichen wählen.")
    salt = secrets.token_bytes(16)
    return json.dumps({"salt": salt.hex(), "hash": hash_password(password, salt)})


def password_matches(password, record):
    if not isinstance(password, str) or len(password) > 256 or not record:
        return False
    try:
        data = json.loads(record)
        return hmac.compare_digest(hash_password(password, bytes.fromhex(data["salt"])), data["hash"])
    except (ValueError, KeyError, TypeError):
        return False


def validate_permissions(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or v not in PERMISSIONS for v in value):
        raise ValueError("Bitte ausschließlich Rechte aus dem Rechtekatalog verwenden.")
    return sorted(set(value))


def validate_preferences(value, current=None):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_PREFERENCES):
        raise ValueError("Unbekannte persönliche Einstellung.")
    result = {**DEFAULT_PREFERENCES, **(current or {}), **value}
    if result["identity_order"] not in {"name", "id"} or result["theme"] not in {"retro", "dark", "midnight", "graphite", "paper"} or type(result["reduced_motion"]) is not bool:
        raise ValueError("Bitte gültige Anzeige-Reihenfolge, Design und Animationseinstellung wählen.")
    return result


def _display(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 64 or any(ord(c) < 32 for c in value):
        raise ValueError("Der Anzeigename braucht 1–64 druckbare Zeichen.")
    return value.strip()


def has(user, permission):
    return bool(user and user.get("enabled") and (user.get("is_owner") or permission in user.get("permissions", [])))


def require(user, permission):
    if not has(user, permission):
        label = next((label for key, label, _ in PERMISSION_CATALOG if key == permission), permission)
        raise AuthorizationError("Dir fehlt dieses Recht: " + label)


def is_user_manager(user):
    return bool(user and user.get("enabled") and (user.get("is_owner") or USER_PERMISSIONS.intersection(user.get("permissions", []))))


def manageable_reason(actor, target):
    if not is_user_manager(actor):
        return "Dir wurde keine Webkonto-Verwaltung freigegeben."
    if actor.get("is_owner"):
        return "Bastis Vollzugriff und Anmeldename bleiben unveränderbar." if target.get("is_owner") else None
    if actor["id"] == target["id"]:
        return "Deine eigenen Rechte kannst du nicht über die Benutzerverwaltung ändern."
    if target.get("is_owner"):
        return "Bastis Konto ist dauerhaft geschützt."
    if USER_PERMISSIONS.intersection(target.get("permissions", [])):
        return "Andere Webverwalter kann ausschließlich Basti verwalten."
    if set(target.get("permissions", [])) - set(actor.get("permissions", [])):
        return "Dieses Konto hat Rechte außerhalb deiner Freigaben. Nur Basti kann es verwalten."
    return None


def management_capabilities(actor):
    return {**{"can_" + name: has(actor, "users." + name) for name in ("create", "edit", "password", "permissions", "disable")},
            "grantable_permissions": sorted(PERMISSIONS if actor.get("is_owner") else set(actor.get("permissions", [])) - USER_PERMISSIONS),
            "rules": ("Nur Basti vergibt Rechte zur Webkonto-Verwaltung. Delegierte Verwalter bearbeiten nur fremde normale Konten, "
                      "deren Rechte innerhalb ihrer eigenen Freigaben liegen. Sie dürfen nur eigene Funktionsrechte weitergeben; "
                      "Basti, das eigene Konto und andere Verwalter sind geschützt. Discord-Verwaltungs- und Schutzrollen bleiben Basti vorbehalten.")}


def validate_grant(actor, permissions):
    perms = validate_permissions(permissions)
    if not actor.get("is_owner"):
        if USER_PERMISSIONS.intersection(perms):
            raise AuthorizationError("Rechte zur Webkonto-Verwaltung darf ausschließlich Basti vergeben.")
        if set(perms) - set(actor.get("permissions", [])):
            raise AuthorizationError("Du kannst nur Funktionsrechte weitergeben, die du selbst besitzt.")
    return perms


def authorize_action(user, kind, payload):
    if not user or not user.get("enabled"):
        raise AuthorizationError("Dieses Webkonto ist nicht aktiv.")
    if kind == "settings":
        patch = payload.get("patch")
        if not isinstance(patch, dict) or not patch:
            raise ValueError("Einstellungen fehlen.")
        for key in patch:
            if key in OWNER_SETTINGS:
                if not user.get("is_owner"):
                    raise AuthorizationError("Verwaltungs- und Schutzrollen darf nur Basti ändern.")
            elif key not in SETTING_PERMISSIONS:
                raise ValueError("Diese Einstellung kann hier nicht geändert werden.")
            else:
                require(user, SETTING_PERMISSIONS[key])
    elif kind == "moderation":
        command = payload.get("command", payload.get("action"))
        if command not in {"ban", "unban", "timeout", "kick", "untimeout", "reinvite"}:
            raise ValueError("Unbekannte Moderationsaktion.")
        require(user, "moderate." + command)
        if command == "unban" and payload.get("notify") is True:
            require(user, "moderate.reinvite")
    elif kind in {"scan", "sync", "send_embed"}:
        require(user, {"scan": "run.scan", "sync": "run.sync", "send_embed": "send.messages"}[kind])
    else:
        raise ValueError("Unbekannte Funktion.")


def public_user(user):
    if not user:
        return None
    return {key: user[key] for key in ("id", "username", "display_name", "is_owner", "enabled", "permissions", "preferences")}


class DashboardAuth:
    def __init__(self, db):
        self.db = db
        # The bot and web process may start at the same time; schema changes are serialized.
        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS dashboard_users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE, display_name TEXT NOT NULL,
                password TEXT NOT NULL, is_owner INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
                permissions TEXT NOT NULL DEFAULT '[]', preferences TEXT NOT NULL DEFAULT '{}',
                auth_version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS dashboard_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, actor_id TEXT,
                actor_username TEXT, operation TEXT NOT NULL, target TEXT, details TEXT NOT NULL DEFAULT '{}')""")
            for table, column, sql in (
                ("dashboard_sessions", "user_id", "TEXT"), ("dashboard_sessions", "user_version", "INTEGER NOT NULL DEFAULT 0"),
                ("dashboard_actions", "actor_id", "TEXT"), ("dashboard_actions", "actor_version", "INTEGER NOT NULL DEFAULT 0"),
                ("dashboard_actions", "actor_username", "TEXT")):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql}")
            version = db.execute("SELECT value FROM dashboard_meta WHERE key='auth_schema'").fetchone()
            if not version or version[0] != "2":
                legacy = db.execute("SELECT value FROM dashboard_meta WHERE key='password'").fetchone()
                if legacy:
                    now = time.time()
                    db.execute("INSERT OR IGNORE INTO dashboard_users VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (OWNER_ACCOUNT_ID, "basti", "Basti", legacy[0], 1, 1, "[]", json.dumps(DEFAULT_PREFERENCES), 1, now, now))
                db.execute("DELETE FROM dashboard_sessions")
                db.execute("UPDATE dashboard_actions SET status='cancelled',result=?,updated=? WHERE actor_id IS NULL AND status IN ('pending','running')",
                           (json.dumps({"text": "Alter Auftrag ohne Webkonto wurde bei der Benutzerumstellung verworfen."}), time.time()))
                db.execute("INSERT OR REPLACE INTO dashboard_meta VALUES ('auth_schema','2')")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS dashboard_one_owner ON dashboard_users(is_owner) WHERE is_owner=1")
            db.execute("""CREATE TRIGGER IF NOT EXISTS dashboard_owner_identity_insert BEFORE INSERT ON dashboard_users
                WHEN NEW.is_owner=1 AND (NEW.id!='owner' OR NEW.username!='basti')
                BEGIN SELECT RAISE(ABORT,'Nur Basti kann Owner sein'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS dashboard_owner_identity_update BEFORE UPDATE ON dashboard_users
                WHEN NEW.is_owner=1 AND (NEW.id!='owner' OR NEW.username!='basti')
                BEGIN SELECT RAISE(ABORT,'Nur Basti kann Owner sein'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS dashboard_protect_owner_update BEFORE UPDATE ON dashboard_users
                WHEN OLD.id='owner' AND (NEW.id!='owner' OR NEW.username!='basti' OR NEW.is_owner!=1 OR NEW.enabled!=1)
                BEGIN SELECT RAISE(ABORT,'Owner-Konto ist unveraenderbar'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS dashboard_protect_owner_delete BEFORE DELETE ON dashboard_users
                WHEN OLD.id='owner' BEGIN SELECT RAISE(ABORT,'Owner-Konto kann nicht geloescht werden'); END""")

    def get(self, identity):
        row = self.db.execute("SELECT * FROM dashboard_users WHERE id=?", (identity,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["is_owner"], value["enabled"] = bool(value["is_owner"]), bool(value["enabled"])
        value["permissions"] = sorted(PERMISSIONS) if value["is_owner"] else json.loads(value["permissions"])
        value["preferences"] = {**DEFAULT_PREFERENCES, **json.loads(value["preferences"])}
        return value

    def by_username(self, username):
        if not isinstance(username, str):
            return None
        row = self.db.execute("SELECT id FROM dashboard_users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
        return self.get(row[0]) if row else None

    def users(self, actor=None):
        if actor is not None:
            actor = self.get(actor.get("id")) or {}
            if not is_user_manager(actor):
                raise AuthorizationError("Dir wurde keine Webkonto-Verwaltung freigegeben.")
        result = [public_user(self.get(row[0])) for row in self.db.execute("SELECT id FROM dashboard_users ORDER BY is_owner DESC,username")]
        if actor is not None:
            for user in result:
                reason = manageable_reason(actor, user)
                user.update(manageable=reason is None, management_reason=reason)
        return result

    def audit(self, actor, operation, target=None, details=None):
        with self.db:
            self.db.execute("INSERT INTO dashboard_audit(created,actor_id,actor_username,operation,target,details) VALUES (?,?,?,?,?,?)",
                (time.time(), actor.get("id") if actor else None, actor.get("username") if actor else None, operation, target, json.dumps(details or {}, ensure_ascii=False)))

    def setup_owner(self, record):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM dashboard_users WHERE id=?", (OWNER_ACCOUNT_ID,)).fetchone():
                return False
            now = time.time()
            self.db.execute("INSERT INTO dashboard_users VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (OWNER_ACCOUNT_ID, "basti", "Basti", record, 1, 1, "[]", json.dumps(DEFAULT_PREFERENCES), 1, now, now))
            self.db.execute("INSERT OR REPLACE INTO dashboard_meta VALUES ('password',?)", (record,))
        self.audit(self.get(OWNER_ACCOUNT_ID), "owner_setup", OWNER_ACCOUNT_ID)
        return True

    def create_user(self, actor, *, username, display_name, record, permissions, enabled=True):
        actor = self.get(actor.get("id")) or {}
        require(actor, "users.create")
        if not isinstance(username, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,31}", username):
            raise ValueError("Benutzername: 3–32 Kleinbuchstaben, Ziffern, Punkt, _ oder -.")
        if username in {"basti", "owner"} or self.by_username(username):
            raise ValueError("Dieser Benutzername ist bereits vergeben oder reserviert.")
        if type(enabled) is not bool:
            raise ValueError("Aktiviert muss wahr oder falsch sein.")
        if not enabled:
            require(actor, "users.disable")
        perms, name = validate_grant(actor, permissions), _display(display_name)
        if perms:
            require(actor, "users.permissions")
        identity, now = uuid.uuid4().hex, time.time()
        with self.db:
            self.db.execute("INSERT INTO dashboard_users VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (identity, username, name, record, 0, int(enabled), json.dumps(perms), json.dumps(DEFAULT_PREFERENCES), 1, now, now))
        self.audit(actor, "user_create", identity, {"username": username, "permissions": perms, "enabled": enabled})
        return self.get(identity)

    def update_user(self, actor, identity, patch, record=None):
        actor = self.get(actor.get("id")) or {}
        if not is_user_manager(actor):
            raise AuthorizationError("Dir wurde keine Webkonto-Verwaltung freigegeben.")
        if not isinstance(patch, dict) or set(patch) - {"display_name", "password", "permissions", "enabled"}:
            raise ValueError("Unbekannte Kontoeinstellung. Benutzername und Owner-Status bleiben unverändert.")
        user = self.get(identity)
        if not user:
            raise ValueError("Webkonto wurde nicht gefunden.")
        reason = manageable_reason(actor, user)
        if not actor.get("is_owner") and reason:
            raise AuthorizationError(reason)
        if user["is_owner"] and ({"permissions", "enabled", "password"} & set(patch)):
            raise ValueError("Bastis Rechte bleiben vollständig aktiv. Das eigene Passwort wird mit dem aktuellen Passwort geändert.")
        for key in patch:
            require(actor, {"display_name": "users.edit", "password": "users.password", "permissions": "users.permissions", "enabled": "users.disable"}[key])
        name = _display(patch.get("display_name", user["display_name"]))
        perms = validate_grant(actor, patch["permissions"]) if "permissions" in patch else user["permissions"]
        enabled = patch.get("enabled", user["enabled"])
        if type(enabled) is not bool:
            raise ValueError("Aktiviert muss wahr oder falsch sein.")
        revoke = bool({"password", "permissions", "enabled"} & set(patch))
        if "password" in patch and not record:
            raise ValueError("Neues Passwort fehlt.")
        with self.db:
            self.db.execute("UPDATE dashboard_users SET display_name=?,password=?,permissions=?,enabled=?,auth_version=?,updated=? WHERE id=?",
                (name, record or user["password"], json.dumps(perms), int(enabled), user["auth_version"] + int(revoke), time.time(), identity))
            if revoke:
                self.db.execute("DELETE FROM dashboard_sessions WHERE user_id=?", (identity,))
        self.audit(actor, "user_update", identity, {"fields": sorted(patch), "sessions_revoked": revoke})
        return self.get(identity)

    def change_password(self, identity, record):
        user = self.get(identity)
        with self.db:
            self.db.execute("UPDATE dashboard_users SET password=?,auth_version=auth_version+1,updated=? WHERE id=?", (record, time.time(), identity))
            self.db.execute("DELETE FROM dashboard_sessions WHERE user_id=?", (identity,))
            if identity == OWNER_ACCOUNT_ID:
                self.db.execute("INSERT OR REPLACE INTO dashboard_meta VALUES ('password',?)", (record,))
        self.audit(user, "password_change", identity)
        return self.get(identity)

    def preferences(self, identity, patch):
        user = self.get(identity)
        preferences = validate_preferences(patch, user["preferences"])
        with self.db:
            self.db.execute("UPDATE dashboard_users SET preferences=?,updated=? WHERE id=?", (json.dumps(preferences), time.time(), identity))
        return self.get(identity)


def filter_snapshots(snapshots, user):
    if user.get("is_owner"):
        return copy.deepcopy(snapshots)
    if not user.get("permissions"):
        return []
    output = []
    editable = {key for key, permission in SETTING_PERMISSIONS.items() if has(user, permission)}
    readable = set(SETTING_PERMISSIONS) | OWNER_SETTINGS if has(user, "view.settings") else editable
    for raw in snapshots:
        bot = {key: raw[key] for key in ("bot", "updated", "online", "name", "owner_id") if key in raw}
        bot["guilds"] = []
        if readable:
            bot["schema"] = {key: value for key, value in raw.get("schema", {}).items() if key in readable}
        for key, permissions in (("command_defaults", ("edit.commands", "run.sync")), ("channel_labels", ("edit.channels",)), ("template_labels", ("edit.embeds", "send.messages"))):
            if any(has(user, permission) for permission in permissions) or has(user, "view.settings"):
                bot[key] = copy.deepcopy(raw.get(key, {}))
        for source in raw.get("guilds", []):
            guild = {key: source[key] for key in ("id", "name", "icon", "owner_present") if key in source}
            if readable:
                guild["settings"] = {key: copy.deepcopy(value) for key, value in source.get("settings", {}).items() if key in readable}
            if has(user, "view.analytics"):
                for key in ("stats", "leaders"):
                    guild[key] = copy.deepcopy(source.get(key, [] if key == "leaders" else {}))
            elif has(user, "view.overview"):
                guild["stats"] = {key: value for key, value in source.get("stats", {}).items() if key in {"members", "active_members"}}
            if has(user, "view.logs"):
                for key in ("events", "moderation", "index_count", "scans"):
                    if key in source:
                        guild[key] = copy.deepcopy(source[key])
            elif has(user, "run.scan"):
                for key in ("index_count", "scans"):
                    if key in source:
                        guild[key] = copy.deepcopy(source[key])
            moderates = any(has(user, permission) for permission in MODERATION_PERMISSIONS)
            if has(user, "view.logs") or moderates:
                guild["moderation_history"] = copy.deepcopy(source.get("moderation_history", []))
            if has(user, "view.members") or moderates:
                member_fields = {"id", "name", "username", "display_name", "role_ids", "admin", "bot", "protected", "owner", "timed_out_until"}
                guild["members"] = [{key: copy.deepcopy(value) for key, value in member.items() if key in member_fields}
                                    for member in source.get("members", [])]
                if "member_sync" in source:
                    guild["member_sync"] = copy.deepcopy(source["member_sync"])
            if has(user, "view.members") or has(user, "edit.roles") or has(user, "view.settings") or moderates:
                guild["roles"] = copy.deepcopy(source.get("roles", []))
            if readable or has(user, "send.messages") or has(user, "moderate.reinvite"):
                guild["channels"] = copy.deepcopy(source.get("channels", []))
            bot["guilds"].append(guild)
        output.append(bot)
    return output
