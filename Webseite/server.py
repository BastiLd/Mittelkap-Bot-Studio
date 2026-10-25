"""Private local control panel, backed by the bots' authenticated command queue."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from aiohttp import web

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "Jarvis"))
from botapp.control_bus import ControlBus, control_path
from botapp.instance import InstanceLock
from botapp.runtime import read_state, write_state
from botapp.dashboard_auth import (OWNER_ACCOUNT_ID, AuthorizationError, hash_password, password_record, password_matches,
    public_user, catalog, has, require, authorize_action, filter_snapshots, is_user_manager, management_capabilities)

COOKIE = "mittelkap_session"
SESSION_SECONDS = 8 * 60 * 60


def session(request):
    raw = request.cookies.get(COOKIE, "")
    digest = hashlib.sha256(raw.encode()).hexdigest()
    bus = request.app["bus"]
    row = bus.db.execute("SELECT * FROM dashboard_sessions WHERE id=? AND expires>?", (digest, time.time())).fetchone()
    if not row:
        return None
    user = bus.auth.get(row["user_id"])
    if not user or not user["enabled"] or user["auth_version"] != row["user_version"]:
        return None
    return {**dict(row), "user": user}


def current_user(request):
    auth = session(request)
    if not auth:
        raise AuthorizationError("Bitte erneut anmelden.")
    return auth["user"]


def account_manager(request):
    user = current_user(request)
    if not is_user_manager(user):
        raise AuthorizationError("Dir wurde keine Webkonto-Verwaltung freigegeben.")
    return user


@web.middleware
async def guard(request, handler):
    # Reject foreign Host/Origin values (including DNS rebinding), even on localhost.
    valid_hosts = request.app['hosts']
    if request.host not in valid_hosts:
        return web.json_response({"error": "Diese Adresse ist für das lokale Dashboard nicht freigegeben."}, status=403)
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("Origin") not in request.app['origins']:
            return web.json_response({"error": "Ungültiger Anfrageursprung."}, status=403)
        if request.content_type != "application/json":
            return web.json_response({"error": "JSON-Anfrage erforderlich."}, status=415)
    public = {"/api/auth", "/api/login", "/api/setup"}
    if request.path.startswith("/api/") and request.path not in public:
        auth = session(request)
        if not auth:
            return web.json_response({"error": "Bitte zuerst anmelden."}, status=401)
        if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), auth["csrf"]):
            return web.json_response({"error": "Sitzung ungültig. Bitte Seite neu laden."}, status=403)
    try:
        response = await handler(request)
    except AuthorizationError as exc:
        response = web.json_response({"error": str(exc)}, status=403)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        response = web.json_response({"error": str(exc)[:400] or "Eingabe prüfen."}, status=400)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data: blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"})
    return response


async def json_object(request):
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError("Die Anfrage muss ein JSON-Objekt enthalten.")
    return data


async def auth_info(request):
    auth = session(request)
    return web.json_response({"configured": bool(request.app["bus"].auth.get(OWNER_ACCOUNT_ID)), "authenticated": bool(auth),
                              "csrf": auth["csrf"] if auth else None, "user": public_user(auth["user"]) if auth else None,
                              "permission_catalog": catalog(), "setup_key_required": bool(request.app['setup_key'])})


def logged_in(request, identity=OWNER_ACCOUNT_ID):
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    bus = request.app["bus"]
    user = bus.auth.get(identity)
    if not user or not user["enabled"]:
        raise AuthorizationError("Dieses Webkonto ist nicht aktiv.")
    with bus.db:
        bus.db.execute("DELETE FROM dashboard_sessions WHERE expires<?", (time.time(),))
        bus.db.execute("INSERT INTO dashboard_sessions(id,csrf,expires,user_id,user_version) VALUES (?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time()+SESSION_SECONDS, user["id"], user["auth_version"]))
    response = web.json_response({"authenticated": True, "csrf": csrf, "user": public_user(user)})
    # Origin was checked by guard; do not trust arbitrary forwarded headers.
    response.set_cookie(COOKIE, token, httponly=True, secure=request.headers.get('Origin', '').startswith('https://'), samesite="Strict", max_age=SESSION_SECONDS, path="/")
    return response


async def setup(request):
    data = await json_object(request)
    setup_key = request.app['setup_key']
    if setup_key:
        if not hmac.compare_digest(str(data.get('setup_key') or ''), setup_key):
            return web.json_response({'error': 'Einrichtungsschlüssel stimmt nicht. Siehe private Dashboard-Konfiguration auf deinem Server.'}, status=403)
    elif request.remote not in {"127.0.0.1", "::1"}:
        return web.json_response({'error': 'Für die Ersteinrichtung auf dem Server DASHBOARD_SETUP_KEY hinterlegen.'}, status=403)
    record = await asyncio.to_thread(password_record, data["password"])
    bus = request.app["bus"]
    if not bus.auth.setup_owner(record):
        return web.json_response({"error": "Passwort ist bereits eingerichtet. Bitte anmelden."}, status=409)
    return logged_in(request)


async def login(request):
    bus = request.app["bus"]
    address = request.remote or "local"
    now = time.time()
    with bus.db:
        bus.db.execute('BEGIN IMMEDIATE')
        bus.db.execute("DELETE FROM dashboard_attempts WHERE created<?", (now-300,))
        attempts = bus.db.execute("SELECT COUNT(*) FROM dashboard_attempts WHERE address=?", (address,)).fetchone()[0]
        if attempts >= 5:
            return web.json_response({"error": "Zu viele Anmeldeversuche. Bitte fünf Minuten warten."}, status=429)
        bus.db.execute('INSERT INTO dashboard_attempts VALUES (?,?)', (address, now))
    data = await json_object(request)
    user = bus.auth.by_username(data.get("username", "basti"))
    # The same response covers unknown, disabled and incorrect-password accounts.
    if not user or not user["enabled"] or not await asyncio.to_thread(password_matches, data.get("password"), user["password"]):
        return web.json_response({"error": "Benutzername oder Passwort stimmt nicht, oder das Konto ist gesperrt."}, status=401)
    latest = bus.auth.get(user["id"])
    if not latest or not latest["enabled"] or latest["auth_version"] != user["auth_version"]:
        return web.json_response({"error": "Das Konto wurde während der Anmeldung geändert. Bitte erneut anmelden."}, status=401)
    with bus.db:
        bus.db.execute("DELETE FROM dashboard_attempts WHERE address=?", (address,))
    bus.auth.audit(user, "login", user["id"])
    return logged_in(request, user["id"])


async def logout(request):
    auth = session(request)
    with request.app["bus"].db:
        request.app["bus"].db.execute("DELETE FROM dashboard_sessions WHERE id=?", (auth["id"],))
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE)
    return response


async def password_change(request):
    bus = request.app["bus"]
    user = current_user(request)
    data = await json_object(request)
    if set(data) - {"current_password", "password"}:
        raise ValueError("Hier kann nur das eigene Passwort geändert werden.")
    if not await asyncio.to_thread(password_matches, data.get("current_password"), user["password"]):
        return web.json_response({"error": "Aktuelles Passwort stimmt nicht."}, status=403)
    record = await asyncio.to_thread(password_record, data["password"])
    if current_user(request)["auth_version"] != user["auth_version"]:
        raise AuthorizationError("Das Konto wurde inzwischen geändert. Bitte erneut anmelden.")
    bus.auth.change_password(user["id"], record)
    return logged_in(request, user["id"])


async def users_list(request):
    actor = account_manager(request)
    return web.json_response({"users": request.app["bus"].auth.users(actor), "catalog": catalog(), "management": management_capabilities(actor)})


async def users_create(request):
    require(current_user(request), "users.create")
    data = await json_object(request)
    if not isinstance(data, dict) or set(data) - {"username", "display_name", "password", "permissions", "enabled"}:
        raise ValueError("Unbekannte Kontoeinstellung.")
    record = await asyncio.to_thread(password_record, data["password"])
    actor = current_user(request)
    user = request.app["bus"].auth.create_user(actor, username=data["username"], display_name=data.get("display_name", data["username"]),
        record=record, permissions=data.get("permissions", []), enabled=data.get("enabled", True))
    return web.json_response({"user": public_user(user)}, status=201)


async def users_update(request):
    actor = account_manager(request)
    data = await json_object(request)
    if "password" in data:
        require(actor, "users.password")
    record = await asyncio.to_thread(password_record, data["password"]) if "password" in data else None
    actor = current_user(request)
    user = request.app["bus"].auth.update_user(actor, request.match_info["identity"], data, record)
    return web.json_response({"user": public_user(user)})


async def preferences_update(request):
    user = current_user(request)
    user = request.app["bus"].auth.preferences(user["id"], await json_object(request))
    return web.json_response({"user": public_user(user), "preferences": user["preferences"]})


async def card_preview(request):
    user = current_user(request)
    if not (has(user, "edit.embeds") or has(user, "send.messages")):
        raise AuthorizationError("Für die Kartenvorschau fehlt das Gestaltungs- oder Versandrecht.")
    data = await json_object(request)
    if data.get("kind") not in {"welcome", "farewell", "birthday"}:
        raise ValueError("Vorschau ist für Willkommen, Abschied und Geburtstag verfügbar.")
    for key, limit in (("name", 100), ("server", 100), ("title", 256)):
        if key == "title" and data.get(key) is None:
            continue  # null deliberately selects the renderer's standard heading.
        if key in data and (not isinstance(data[key], str) or len(data[key]) > limit):
            raise ValueError("Vorschautext ist zu lang oder ungültig.")
    from botapp.image_cards import render_card
    content = await asyncio.to_thread(render_card, data["kind"], name=data.get("name", "Beispielmitglied"),
        server=data.get("server", "MittelKings Universe"), title=data.get("title"), style=data.get("style", data.get("image_style")), sample_avatar=True)
    return web.Response(body=content, content_type="image/png")


async def state(request):
    snapshots = filter_snapshots(request.app["bus"].snapshots(), current_user(request))
    for bot in snapshots:
        if time.time() - bot["updated"] > 15:
            bot["online"] = False
    return web.json_response({"bots": snapshots, "time": time.time(), "version": "3.0", "owner_id": "965593518745731152"})


async def enqueue(request):
    data = await json_object(request)
    bot, guild, kind = data["bot"], str(data["guild"]), data["kind"]
    payload, key = data.get("payload", {}), data.get("request_key", "")
    if bot not in {"jarvis", "ultron"} or not guild.isdecimal() or not isinstance(payload, dict):
        raise ValueError("Bot und Server prüfen.")
    if kind not in {"settings", "sync", "scan", "moderation", "send_embed", "xp"}:
        raise ValueError("Unbekannte Funktion.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key):
        raise ValueError("Anfragekennung fehlt.")
    snapshots = request.app["bus"].snapshots()
    target = next((b for b in snapshots if b["bot"] == bot), None)
    if not target or not target.get("online") or time.time() - target["updated"] > 15:
        raise ValueError("Dieser Bot ist nicht online. Bitte zuerst den Bot starten.")
    if not any(str(g["id"]) == guild for g in target.get("guilds", [])):
        raise ValueError("Dieser Server ist nicht verfügbar.")
    if kind == "settings" and not isinstance(payload.get("patch"), dict):
        raise ValueError("Einstellungen fehlen.")
    if kind in {"moderation", "send_embed", "xp"} and payload.get("confirm") is not True:
        raise ValueError("Bitte die Aktion zuerst prüfen und bestätigen.")
    user = current_user(request)
    authorize_action(user, kind, payload)
    identity = request.app["bus"].enqueue(bot, guild, kind, payload, key, actor_id=user["id"], actor_version=user["auth_version"])
    return web.json_response({"id": identity, "status": "pending"}, status=202)


async def action(request):
    result = request.app["bus"].action(request.match_info["identity"])
    if not result:
        raise web.HTTPNotFound()
    user = current_user(request)
    if not user["is_owner"] and result["actor_id"] != user["id"]:
        raise AuthorizationError("Dieser Auftrag gehört einem anderen Webkonto.")
    if not user["is_owner"]:
        row = request.app["bus"].db.execute("SELECT payload FROM dashboard_actions WHERE id=?", (result["id"],)).fetchone()
        authorize_action(user, result["kind"], json.loads(row["payload"]))
    return web.json_response(result)


async def index(request):
    return web.FileResponse(ROOT / "static" / "index.html")


async def close(app):
    app["bus"].close()


async def process_control(app):
    folder = control_path().parent
    state_file, stop_file = folder/'web-state.json', folder/'web-stop.json'
    identity = uuid.uuid4().hex
    state = {'pid': os.getpid(), 'instance': identity, 'port': app['port'], 'state': 'online'}
    write_state(state_file, state)
    async def watch():
        while True:
            if read_state(stop_file).get('instance') == identity:
                app['stop_event'].set()
                return
            await asyncio.sleep(.3)
    task = asyncio.create_task(watch())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        write_state(state_file, {**state, 'state':'stopped'})
        if read_state(stop_file).get('instance') == identity:
            stop_file.unlink(missing_ok=True)


def create_app(path=None, port=8765, public_url=None, setup_key=None, additional_urls=None):
    app = web.Application(middlewares=[guard], client_max_size=256*1024)
    app["bus"], app["port"] = ControlBus(path), port
    public_url = public_url or os.environ.get('DASHBOARD_PUBLIC_URL', f'http://127.0.0.1:{port}')
    origin = urlsplit(public_url)
    if origin.scheme not in {'http', 'https'} or not origin.hostname or origin.path not in {'','/'} or origin.query or origin.fragment or origin.username or origin.password:
        raise ValueError('DASHBOARD_PUBLIC_URL braucht eine vollständige Basisadresse ohne Pfad, zum Beispiel https://bots.example.com')
    app['hosts'] = {origin.netloc}
    app['origins'] = {f'{origin.scheme}://{origin.netloc}'}
    app['secure'] = origin.scheme == 'https'
    if origin.hostname in {'127.0.0.1','localhost'}:
        app['hosts'].update({f'127.0.0.1:{port}',f'localhost:{port}'})
        app['origins'].update({'http://'+h for h in app['hosts']})
    additional_urls = additional_urls if additional_urls is not None else os.environ.get('DASHBOARD_ADDITIONAL_URLS', '')
    for value in additional_urls.split(','):
        if not value.strip():
            continue
        extra = urlsplit(value.strip())
        if extra.scheme not in {'http', 'https'} or not extra.hostname or '*' in extra.netloc or extra.path not in {'', '/'} or extra.query or extra.fragment or extra.username or extra.password:
            raise ValueError('DASHBOARD_ADDITIONAL_URLS braucht vollständige Basisadressen ohne Pfad, durch Komma getrennt.')
        app['hosts'].add(extra.netloc)
        app['origins'].add(f'{extra.scheme}://{extra.netloc}')
    app['setup_key'] = setup_key if setup_key is not None else os.environ.get('DASHBOARD_SETUP_KEY','')
    app.router.add_get("/", index)
    app.router.add_get("/api/auth", auth_info)
    app.router.add_post("/api/setup", setup)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_post("/api/password", password_change)
    app.router.add_get("/api/users", users_list)
    app.router.add_post("/api/users", users_create)
    app.router.add_patch("/api/users/{identity}", users_update)
    app.router.add_patch("/api/preferences", preferences_update)
    app.router.add_post("/api/card-preview", card_preview)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/actions", enqueue)
    app.router.add_get("/api/actions/{identity}", action)
    app.router.add_static("/static/", ROOT / "static", show_index=False)
    app.on_cleanup.append(close)
    return app


async def serve(app, host, port):
    app['stop_event'] = asyncio.Event()
    runner = web.AppRunner(app, handle_signals=True, access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        print(f'Dashboard erreichbar auf Port {port}.', flush=True)
        await app['stop_event'].wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get('DASHBOARD_PORT', '8765')))
    args = parser.parse_args()
    app = create_app(port=args.port)
    # Cooperative local controller is Windows-only; containers use normal SIGTERM.
    if os.name == 'nt':
        app.cleanup_ctx.append(process_control)
    with InstanceLock(control_path().parent/'web.lock'):
        try:
            asyncio.run(serve(app, os.environ.get('DASHBOARD_HOST','127.0.0.1'), args.port))
        except (KeyboardInterrupt, web.GracefulExit):
            pass
