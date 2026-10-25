from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from botapp.cards import rank_card
from botapp.config import Config
from botapp.instance import InstanceLock
from botapp.runtime import run_client
from botapp.secrets import load_credentials
from botapp.service import Actor, Service
from botapp.store import Store

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Discord-Bot: Grundprüfung und Demo ohne Token; Livebetrieb nur mit --run.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Konfiguration und Bibliotheken prüfen, kein Netzwerk")
    mode.add_argument("--demo", action="store_true", help="Lokale Beispielantworten und Rangkarte erzeugen, kein Netzwerk")
    mode.add_argument("--simulate", metavar="BEFEHL", help="Einen Befehl mit isolierter Demo-Datenbank ausführen")
    mode.add_argument("--run", action="store_true", help="Mit Discord verbinden; benötigt ein eigenes Token")
    mode.add_argument("--sync", action="store_true", help="Nur Slash-Befehle bei Discord aktualisieren, ohne Botbetrieb")
    mode.add_argument("--token-check", action="store_true", help="Token-Dateipfad und Vorhandensein prüfen; keine Tokenwerte, kein Netzwerk")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = Config(ROOT)
        if args.token_check:
            from diagnose import main as diagnose_main
            return diagnose_main()
        credentials_path = load_credentials(ROOT, config.base["persona"])
        if not (args.demo or args.simulate or args.run or args.sync):
            from botapp.discord_client import DiscordBot  # Verify the real adapter can be imported.
            print(f"{config.base['name']}: Konfiguration gültig; Discord-Anbindung importierbar.")
            print(f"Token-Datei: {credentials_path}")
            print("Aktivierte Funktionen: " + ", ".join(config.base["features"]))
            temporary = Store(":memory:")
            try:
                client = DiscordBot(Service(config, temporary))
                names = [command.name for command in client.tree.get_commands()]
                print("Slash-Befehle: " + ", ".join(names))
                if config.base["persona"] == "ultron" and "rang" in names:
                    raise ValueError("/rang ist ausschließlich Jarvis zugeordnet.")
                for command in client.tree.get_commands():
                    command.to_dict(client.tree)
            finally:
                temporary.close()
            print("Bibliotheken: " + ", ".join(f"{p} {importlib.metadata.version(p)}" for p in ("discord.py", "aiohttp", "Pillow", "python-dotenv", "tzdata", "defusedxml")))
            print("Kein Discord-Login ausgeführt. Lokale Demo: python bot.py --demo")
            return 0
        (ROOT / "data").mkdir(exist_ok=True)
        if args.run or args.sync:
            token = os.getenv("DISCORD_TOKEN", "").strip()
            if not token:
                print(f"Kein DISCORD_TOKEN gefunden. Bitte DISCORD_TOKEN= in dieser Datei eintragen und speichern:\n{credentials_path}", file=sys.stderr)
                return 2
            from botapp.discord_client import DiscordBot
            import discord
            if args.sync:
                class RegistrationClient(DiscordBot):
                    async def setup_hook(self):
                        pass  # No gateway, no maintenance and no server messages.
                async def register():
                    store = Store(":memory:")
                    try:
                        async with RegistrationClient(Service(config, store)) as client:
                            await client.login(token)
                            commands = await client.tree.sync()
                            remote = await client.tree.fetch_commands()
                            if {c.name for c in remote} != {c.name for c in commands}:
                                raise RuntimeError("Discord-Befehle stimmen nach der Registrierung nicht überein.")
                            print(config.base["name"] + ": registriert und bei Discord geprüft: " + ", ".join(c.name for c in remote))
                    finally:
                        store.close()
                try:
                    asyncio.run(register())
                except discord.LoginFailure:
                    print(f"Discord lehnt den Token ab. Datei: {credentials_path}", file=sys.stderr)
                    return 2
                return 0
            with InstanceLock(ROOT / "data" / "bot.lock"):
                store = Store(ROOT / "data" / "bot.sqlite3")
                try:
                    store.recover_pending_moderation()
                    client = DiscordBot(Service(config, store))
                    asyncio.run(run_client(client, token, ROOT))
                except discord.LoginFailure:
                    print(f"Discord hat den Token abgelehnt. Bitte den aktuellen Bot-Token in dieser Datei speichern:\n{credentials_path}", file=sys.stderr)
                    return 2
                except discord.PrivilegedIntentsRequired:
                    print("Discord verlangt aktivierte SERVER MEMBERS und MESSAGE CONTENT Intents im Developer Portal.", file=sys.stderr)
                    return 2
                finally:
                    store.close()
            return 0
        store = Store(":memory:") if args.demo else Store(ROOT / "data" / "simulation.sqlite3")
        service = Service(config, store)
        actor = Actor(100, 200, "Beispielmitglied", True, datetime(2026, 1, 1, tzinfo=timezone.utc), "Community")
        try:
            if args.simulate:
                reply = service.handle(actor, args.simulate)
                print(json.dumps(reply.__dict__ if reply else {"info": "Kein passendes Präfix erkannt."}, ensure_ascii=False, indent=2))
            else:
                prefix = "/" if config.base.get("command_mode") == "slash" else config.base["prefixes"][0]
                commands = [f"{prefix}hilfe", f"{prefix}status"]
                for feature, command in (("links", "youtube"), ("birthdays", "geburtstag 27.05."), ("rank", "rang"), ("unban", "entbannen 123456789012345678 Demo"), ("ban", "bannen 123456789012345678 Demo"), ("timeout", "stummschalten 123456789012345678 10m Demo")):
                    if feature in config.base["features"]:
                        commands.append(prefix + command)
                for command in commands:
                    reply = service.handle(actor, command)
                    print(f"\n> {command}\n{reply.title}\n{reply.text}")
                for joined in (True, False):
                    reply = service.member_event(actor.guild, actor.user, actor.name, joined)
                    if reply:
                        print(f"\n> Simuliertes Serverereignis\n{reply.title}\n{reply.text}")
                if "rank" in config.base["features"]:
                    for n in range(137):
                        store.message(actor.guild, actor.user, n, 15, 0, True)
                    store.voice(actor.guild, actor.user, 7440, 1240)
                    store.voice_message(actor.guild, actor.user, 1, 94, 10)
                    preview = ROOT / "preview"
                    preview.mkdir(exist_ok=True)
                    path = preview / "rank-demo.png"
                    path.write_bytes(rank_card(service.rank(actor).rank, "", ""))
                    print(f"\nLokale Rangkarte (fiktive Daten, ein gemeinsames Design): {path}")
                print("Kein Discord-Login, keine externen API-Aufrufe.")
        finally:
            store.close()
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"Startprüfung fehlgeschlagen: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
